(() => {
  const $ = (selector) => document.querySelector(selector);
  const all = (selector) => Array.from(document.querySelectorAll(selector));
  const panels = all(".nav-sol, .mobile-menu, .platform-details");
  document.addEventListener("click", (event) => {
    for (const panel of panels) {
      if (!panel.contains(event.target) || event.target.closest("nav a"))
        panel.open = false;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    for (const panel of panels)
      if (panel.open) {
        panel.open = false;
        panel.querySelector("summary").focus();
      }
  });
  const progress = $(".reading-progress");
  function progressUpdate() {
    const range = document.documentElement.scrollHeight - innerHeight;
    progress.style.transform =
      "scaleX(" +
      (range > 0 ? Math.min(1, Math.max(0, scrollY / range)) : 0) +
      ")";
  }
  addEventListener("scroll", progressUpdate, { passive: true });
  addEventListener("resize", progressUpdate);
  progressUpdate();

  const picks = all("[data-scene]");
  if (picks.length) {
    const images = all(".cover-photos img"),
      toggle = $("#scene-toggle");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let current = 0,
      rotate = !reduced.matches,
      onScreen = true,
      timer;
    function select(index) {
      current = index;
      images.forEach((image, i) =>
        image.classList.toggle("show", i === current),
      );
      picks.forEach((button, i) =>
        button.setAttribute("aria-pressed", String(i === current)),
      );
    }
    function schedule() {
      clearInterval(timer);
      toggle.textContent = rotate ? "Ⅱ" : "▶";
      toggle.setAttribute(
        "aria-label",
        rotate ? "Pause scene rotation" : "Play scene rotation",
      );
      if (rotate && onScreen && !document.hidden)
        timer = setInterval(() => select((current + 1) % picks.length), 7800);
    }
    picks.forEach((button, i) =>
      button.addEventListener("click", () => {
        rotate = false;
        select(i);
        schedule();
      }),
    );
    toggle.addEventListener("click", () => {
      rotate = !rotate;
      schedule();
    });
    reduced.addEventListener("change", () => {
      rotate = !reduced.matches;
      schedule();
    });
    document.addEventListener("visibilitychange", schedule);
    if ("IntersectionObserver" in window)
      new IntersectionObserver((entries) => {
        onScreen = entries[0].isIntersecting;
        schedule();
      }).observe($(".cover"));
    schedule();
  }

  const sectors = all("[data-sector]"),
    sectorPanels = all("[data-sector-panel]");
  sectors.forEach((button, i) =>
    button.addEventListener("click", () => {
      sectors.forEach((item, j) =>
        item.setAttribute("aria-pressed", String(i === j)),
      );
      sectorPanels.forEach((panel, j) => {
        panel.hidden = i !== j;
      });
      $("#sector-index").textContent = String(i + 1).padStart(2, "0") + " / 07";
    }),
  );

  const plan = $("#planner");
  if (plan) {
    function calculate() {
      const [hubs, shifts, riders, days] = [
        "hubs",
        "shifts",
        "riders",
        "days",
      ].map((key) => {
        const value = Number($("#p-" + key).value);
        $("#v-" + key).value = value;
        return value;
      });
      const daily = hubs * shifts * riders,
        weekly = daily * days;
      $("#daily").textContent = daily.toLocaleString("en-IN");
      $("#weekly").textContent = weekly.toLocaleString("en-IN");
      const brief =
        "Delivery hubs: " +
        hubs +
        "\nShifts per hub per day: " +
        shifts +
        "\nRiders per shift: " +
        riders +
        "\nOperating days per week: " +
        days +
        "\nEstimated coverage: " +
        daily +
        " rider shifts per day, " +
        weekly +
        " per week.";
      $("#plan-cta").href = "./partner.html?" + new URLSearchParams({ brief });
    }
    plan.addEventListener("input", calculate);
    calculate();
  }

  const requirement = $("#requirement");
  if (requirement && !requirement.value) {
    const params = new URLSearchParams(location.search);
    if (params.get("brief"))
      requirement.value = params.get("brief").slice(0, 800);
    else if (params.get("sector"))
      requirement.value =
        "Sector: " +
        params.get("sector").slice(0, 70) +
        "\nOur pickup points and shift requirements: ";
    else if (params.get("need") === "ev")
      requirement.value =
        "We need riders and would like to discuss rental EV availability.\nEstimated number of riders who need an EV: ";
  }
  const riderForm = $("#join-form");
  if (riderForm)
    riderForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const body =
        "Hello Qwikserve,\nI would like to ask about joining as a rider.\nCity or area: " +
        $("#r-area").value.trim() +
        "\nVehicle: " +
        $("#r-vehicle").value +
        "\nAvailability: " +
        ($("#r-time").value.trim() || "To discuss");
      $("#r-status").textContent =
        "If no email app opens, call +91 98309 84063 or email info@qwikserve.in.";
      location.href =
        "mailto:info@qwikserve.in?subject=Rider%20joining%20enquiry&body=" +
        encodeURIComponent(body);
    });
})();

const recordPoints = Array.from(document.querySelectorAll("[data-record]"));
const recordPanels = Array.from(
  document.querySelectorAll("[data-record-panel]"),
);
recordPoints.forEach((point, i) =>
  point.addEventListener("click", () => {
    recordPoints.forEach((other, j) =>
      other.setAttribute("aria-pressed", String(i === j)),
    );
    recordPanels.forEach((panel, j) => {
      panel.hidden = i !== j;
    });
  }),
);
