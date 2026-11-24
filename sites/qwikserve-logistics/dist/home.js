const video = document.querySelector("#field-video");
const chapters = Array.from(
  document.querySelectorAll(".chapters [data-start]"),
);
const motion = window.matchMedia("(prefers-reduced-motion: reduce)");

let bufferedSource;
let pendingChapter = null;

function bufferFilm() {
  // Some static hosts serve the entire MP4 without supporting byte-range seeks.
  // A local object URL gives the native scrubber and chapters the same timeline.
  if (!bufferedSource) {
    bufferedSource = fetch(video.querySelector("source").src)
      .then((response) => {
        if (!response.ok) throw new Error("Film unavailable");
        return response.blob();
      })
      .then(
        (blob) =>
          new Promise((resolve, reject) => {
            const resumeTime = video.currentTime;
            const resumePlaying = !video.paused;
            const objectUrl = URL.createObjectURL(blob);
            video.addEventListener(
              "loadedmetadata",
              () => {
                video.currentTime = pendingChapter ?? resumeTime;
                if (resumePlaying && pendingChapter === null)
                  video.play().catch(() => {});
                resolve();
              },
              { once: true },
            );
            video.addEventListener("error", reject, { once: true });
            video.src = objectUrl;
          }),
      );
  }
  return bufferedSource;
}

function canSeekFilm() {
  return (
    video.seekable.length &&
    video.seekable.end(video.seekable.length - 1) >= video.duration - 0.05
  );
}

video.addEventListener(
  "loadedmetadata",
  () => {
    if (!canSeekFilm()) bufferFilm().catch(() => {});
  },
  { once: true },
);

async function playFrom(seconds) {
  pendingChapter = seconds;
  try {
    if (seconds > 0 && !canSeekFilm()) await bufferFilm();
    if (pendingChapter !== seconds) return;
    video.currentTime = seconds;
    await video.play();
  } catch {
    video.focus({ preventScroll: true });
  } finally {
    if (pendingChapter === seconds) pendingChapter = null;
  }
}

document.querySelector("#watch-film").addEventListener("click", () => {
  playFrom(0);
});

for (const link of chapters) {
  link.addEventListener("click", (event) => {
    if (!video.canPlayType("video/mp4")) return;
    event.preventDefault();
    playFrom(Number(link.dataset.start));
    if (window.matchMedia("(max-width: 740px)").matches) {
      video.scrollIntoView({
        block: "center",
        behavior: motion.matches ? "instant" : "smooth",
      });
    }
  });
}

function syncChapter() {
  const active = chapters
    .filter((link) => Number(link.dataset.start) <= video.currentTime)
    .pop();
  for (const link of chapters) {
    if (link === active) link.setAttribute("aria-current", "step");
    else link.removeAttribute("aria-current");
  }
}
video.addEventListener("timeupdate", syncChapter);
video.addEventListener("seeked", syncChapter);

if ("IntersectionObserver" in window && !motion.matches) {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);

        entry.target.classList.add("reveal");
      }
    },
    { threshold: 0.2 },
  );
  document
    .querySelectorAll(".service-card")
    .forEach((item) => observer.observe(item));
}
