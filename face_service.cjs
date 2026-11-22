"use strict";

const crypto = require("node:crypto");
const http = require("node:http");
const path = require("node:path");

const canvas = require("@napi-rs/canvas");
const faceapi = require("@vladmandic/face-api/dist/face-api.node-wasm.js");
const tf = require("@tensorflow/tfjs");
const wasm = require("@tensorflow/tfjs-backend-wasm");

const HOST = "127.0.0.1";
const PORT = Number(process.env.FIPCONNECT_FACE_SERVICE_PORT || 5018);
const TOKEN = process.env.FIPCONNECT_FACE_SERVICE_TOKEN || "";
const MAX_REQUEST_BYTES = 1_000_000;
const MAX_IMAGE_BYTES = 700_000;
const MAX_IMAGE_PIXELS = 4_000_000;
const FACE_MATCH_THRESHOLD = 0.6;
const MODEL_DIRECTORY = path.resolve(
  path.dirname(require.resolve("@vladmandic/face-api")),
  "..",
  "model"
);
const WASM_DIRECTORY = path.dirname(
  require.resolve("@tensorflow/tfjs-backend-wasm")
);

if (!/^[\da-f]{64}$/.test(TOKEN)) {
  throw new Error("FIPCONNECT_FACE_SERVICE_TOKEN must be a 64-character hex token.");
}
if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
  throw new Error("FIPCONNECT_FACE_SERVICE_PORT must be a valid port number.");
}

faceapi.env.monkeyPatch({
  Canvas: canvas.Canvas,
  Image: canvas.Image,
  ImageData: canvas.ImageData,
});

function authorized(request) {
  const supplied = request.headers.authorization || "";
  const expected = `Bearer ${TOKEN}`;
  const suppliedBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  return suppliedBytes.length === expectedBytes.length
    && crypto.timingSafeEqual(suppliedBytes, expectedBytes);
}

function sendJson(response, status, body) {
  const data = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": data.length,
    "Cache-Control": "no-store",
  });
  response.end(data);
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", chunk => {
      body += chunk;
      if (Buffer.byteLength(body) > MAX_REQUEST_BYTES) {
        reject(Object.assign(new Error("Request is too large."), { status: 413 }));
        request.destroy();
      }
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(Object.assign(new Error("Request must contain valid JSON."), { status: 400 }));
      }
    });
    request.on("error", reject);
  });
}

async function decodeImage(encodedImage) {
  if (
    typeof encodedImage !== "string"
    || !encodedImage
    || encodedImage.length > MAX_IMAGE_BYTES * 1.4
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encodedImage)
  ) {
    throw Object.assign(new Error("Could not read the camera capture. Please try again."), { status: 400 });
  }
  const bytes = Buffer.from(encodedImage, "base64");
  if (
    !bytes.length
    || bytes.length > MAX_IMAGE_BYTES
    || bytes.toString("base64") !== encodedImage
  ) {
    throw Object.assign(new Error("The camera capture is too large or invalid."), { status: 400 });
  }
  const isJpeg = bytes[0] === 0xff && bytes[1] === 0xd8;
  const isPng = bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  if (!isJpeg && !isPng) {
    throw Object.assign(new Error("Only JPEG or PNG camera captures are supported."), { status: 400 });
  }
  let image;
  try {
    image = await canvas.loadImage(bytes);
  } catch {
    throw Object.assign(new Error("Could not read the camera capture. Please try again."), { status: 400 });
  }
  if (
    !image.width
    || !image.height
    || image.width * image.height > MAX_IMAGE_PIXELS
  ) {
    throw Object.assign(new Error("The camera capture resolution is too high."), { status: 400 });
  }
  return image;
}

async function extractEmbedding(encodedImage) {
  const image = await decodeImage(encodedImage);
  const faces = await faceapi
    .detectAllFaces(image, new faceapi.SsdMobilenetv1Options({ minConfidence: 0.5 }))
    .withFaceLandmarks()
    .withFaceDescriptors();
  if (faces.length !== 1) {
    const message = faces.length
      ? "Only one face may be in the camera frame."
      : "Face not recognized. Look at the camera and try again.";
    throw Object.assign(new Error(message), { status: 400 });
  }
  const descriptor = Array.from(faces[0].descriptor);
  if (descriptor.length !== 128 || !descriptor.every(Number.isFinite)) {
    throw new Error("Could not create a valid JavaScript face template.");
  }
  return descriptor;
}

async function handle(request, response) {
  if (!authorized(request)) {
    sendJson(response, 401, { error: "Unauthorized." });
    return;
  }
  if (request.method === "GET" && request.url === "/health") {
    sendJson(response, 200, { ready: true });
    return;
  }
  if (request.method !== "POST" || !["/extract", "/verify", "/match"].includes(request.url)) {
    sendJson(response, 404, { error: "Not found." });
    return;
  }
  try {
    const payload = await readJson(request);
    const embedding = await extractEmbedding(payload.image);
    if (request.url === "/extract") {
      sendJson(response, 200, { embedding });
      return;
    }
    if (request.url === "/match") {
      if (
        !Array.isArray(payload.embeddings)
        || !payload.embeddings.length
        || !payload.embeddings.every(candidate => (
          Array.isArray(candidate)
          && candidate.length === 128
          && candidate.every(value => typeof value === "number" && Number.isFinite(value))
        ))
      ) {
        sendJson(response, 400, { error: "One or more saved face templates are invalid." });
        return;
      }
      const descriptors = payload.embeddings.map(candidate => (
        new Float32Array(candidate)
      ));
      const distances = descriptors.map((descriptor, index) => ({
        index,
        distance: faceapi.euclideanDistance(
          new Float32Array(embedding),
          descriptor
        ),
      }));
      const closest = distances.reduce((best, candidate) => (
        candidate.distance < best.distance ? candidate : best
      ));
      sendJson(response, 200, {
        matchedIndex: closest.distance <= FACE_MATCH_THRESHOLD ? closest.index : null,
      });
      return;
    }
    if (
      !Array.isArray(payload.embedding)
      || payload.embedding.length !== 128
      || !payload.embedding.every(value => typeof value === "number" && Number.isFinite(value))
    ) {
      sendJson(response, 400, { error: "The saved face template is incompatible with the JavaScript model." });
      return;
    }
    const distance = faceapi.euclideanDistance(
      new Float32Array(embedding),
      new Float32Array(payload.embedding)
    );
    sendJson(response, 200, { verified: distance <= FACE_MATCH_THRESHOLD });
  } catch (error) {
    const status = Number.isInteger(error.status) ? error.status : 500;
    if (status >= 500) console.error("Face recognition request failed:", error);
    sendJson(response, status, {
      error: status >= 500
        ? "May error sa JavaScript face recognition service."
        : error.message,
    });
  }
}

async function start() {
  wasm.setWasmPaths(`${WASM_DIRECTORY}${path.sep}`);
  await tf.setBackend("wasm");
  await tf.ready();
  await faceapi.nets.ssdMobilenetv1.loadFromDisk(MODEL_DIRECTORY);
  await faceapi.nets.faceLandmark68Net.loadFromDisk(MODEL_DIRECTORY);
  await faceapi.nets.faceRecognitionNet.loadFromDisk(MODEL_DIRECTORY);
  const server = http.createServer((request, response) => {
    handle(request, response).catch(error => {
      console.error("Unhandled face recognition service error:", error);
      if (!response.headersSent) {
        sendJson(response, 500, { error: "May error sa JavaScript face recognition service." });
      } else {
        response.destroy();
      }
    });
  });
  server.listen(PORT, HOST, () => {
    console.error(`JavaScript face recognition ready on http://${HOST}:${PORT}`);
  });
}

start().catch(error => {
  console.error("Unable to initialize JavaScript face recognition:", error);
  process.exitCode = 1;
});
