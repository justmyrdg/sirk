(() => {
  "use strict";

  // Old single-page links (/#inquiry, /#availability?…, /#status) now have real pages.
  const oldRoutes = { inquiry: "/inquire", availability: "/availability", status: "/status" };
  const [route, query] = location.hash.slice(1).split("?");
  if (oldRoutes[route]) {
    location.replace(oldRoutes[route] + (query ? `?${query}` : ""));
    return;
  }

  // Photo gallery arrows and "n / total" counter.
  const gallery = document.querySelector(".photo-gallery");
  const counter = document.querySelector(".gallery-count");
  document.querySelectorAll("[data-gallery-move]").forEach(button => {
    button.addEventListener("click", () => {
      if (gallery) gallery.scrollBy({ left: gallery.clientWidth * Number(button.dataset.galleryMove), behavior: "smooth" });
    });
  });
  if (gallery && counter) {
    gallery.addEventListener("scroll", () => {
      const current = Math.min(gallery.children.length, Math.round(gallery.scrollLeft / gallery.clientWidth) + 1);
      counter.textContent = `${current} / ${gallery.children.length}`;
    });
  }

  // Ask before submitting forms marked with data-confirm.
  document.addEventListener("submit", event => {
    const message = event.target.dataset && event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
