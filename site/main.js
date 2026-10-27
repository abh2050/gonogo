// GoNoGo site. No dependencies. Everything still reads without this file: it only adds motion and the diagram viewer.

(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Header turns solid after the hero.
  const nav = document.getElementById("nav");
  const onScroll = () => nav.classList.toggle("solid", scrollY > 40);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Sections rise in once.
  const reveals = document.querySelectorAll(".reveal");
  if (reduced || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("in"));
  } else {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    reveals.forEach((el) => io.observe(el));
  }

  // Count-up numbers.
  const count = (el) => {
    const to = parseFloat(el.dataset.count);
    const suffix = el.dataset.suffix || "";
    const decimals = String(to).includes(".") ? 1 : 0;
    if (reduced) return;
    const start = performance.now();
    const run = (t) => {
      const k = Math.min(1, (t - start) / 1400);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = (to * eased).toFixed(decimals) + suffix;
      if (k < 1) requestAnimationFrame(run);
    };
    requestAnimationFrame(run);
  };
  const numbers = document.querySelectorAll("[data-count]");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            count(e.target);
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.6 },
    );
    numbers.forEach((el) => io.observe(el));
  }

  // Benchmark bars grow from the scored data. The HTML already holds the same numbers, so a failed fetch changes nothing.
  const rows = document.querySelectorAll("#bars .bar-row");
  const grow = (data) =>
    rows.forEach((row) => {
      const value = data && data[row.dataset.key] ? data[row.dataset.key].accuracy : parseFloat(row.dataset.value);
      row.querySelector(".fill").style.width = value + "%";
      row.querySelector(".val").textContent = value + "%";
    });
  const bars = document.getElementById("bars");
  if (bars) {
    const load = fetch("assets/data.json").then((r) => r.json()).catch(() => null);
    const show = () => load.then(grow);
    if (reduced || !("IntersectionObserver" in window)) show();
    else {
      const io = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            show();
            io.disconnect();
          }
        },
        { threshold: 0.35 },
      );
      io.observe(bars);
    }
  }

  // Looping clips play only while on screen.
  const clips = document.querySelectorAll("video[data-play]");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          const v = e.target;
          if (e.isIntersecting && !reduced) v.play().catch(() => {});
          else v.pause();
        }),
      { threshold: 0.25 },
    );
    clips.forEach((v) => io.observe(v));
  }
  if (reduced) document.querySelectorAll("video[autoplay]").forEach((v) => v.pause());

  // Architecture tabs.
  const tabs = [...document.querySelectorAll(".tab")];
  const select = (tab) => {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
  };
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(t));
    t.addEventListener("keydown", (e) => {
      const next = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!next) return;
      const target = tabs[(i + next + tabs.length) % tabs.length];
      select(target);
      target.focus();
    });
  });

  // Click a diagram to enlarge it.
  const box = document.getElementById("lightbox");
  const big = box.querySelector("img");
  document.querySelectorAll("button.zoom").forEach((b) =>
    b.addEventListener("click", () => {
      const img = b.querySelector("img");
      big.src = img.src;
      big.alt = img.alt;
      box.showModal();
    }),
  );
  box.addEventListener("click", () => box.close());
})();
