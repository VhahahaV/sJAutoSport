type ConfettiOptions = {
  particleCount?: number;
  spread?: number;
  origin?: { x: number; y: number };
  durationMs?: number;
};

const CONFETTI_COLORS = [
  "#F9A8D4",
  "#F472B6",
  "#C084FC",
  "#60A5FA",
  "#34D399",
  "#FBBF24",
  "#F87171",
];

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

const DEFAULT_INTERACTIVE_SELECTORS = [
  "a.nav-link",
  "button",
  ".button",
  ".toggle-button",
  ".preset-selector__button",
  ".card",
  ".panel",
] as const;

const SPARKLE_COLORS = [
  "#FBBF24",
  "#F472B6",
  "#60A5FA",
  "#34D399",
  "#C084FC",
  "#F97316",
];

export const fireConfetti = (options: ConfettiOptions = {}) => {
  if (typeof document === "undefined") return;

  const root = document.createElement("div");
  root.className = "confetti-overlay";

  const originX = clamp01(options.origin?.x ?? 0.5);
  const originY = clamp01(options.origin?.y ?? 0.35);
  root.style.setProperty("--confetti-origin-x", `${originX * 100}%`);
  root.style.setProperty("--confetti-origin-y", `${originY * 100}%`);

  document.body.appendChild(root);

  const count = Math.max(12, options.particleCount ?? 32);
  const baseDuration = options.durationMs ?? 1800;
  const spread = options.spread ?? 120;

  for (let index = 0; index < count; index += 1) {
    const particle = document.createElement("span");
    particle.className = "confetti-particle";
    const color = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
    particle.style.setProperty("--confetti-color", color);

    const angle = (Math.random() - 0.5) * spread;
    const radians = (angle * Math.PI) / 180;
    const thrust = 260 + Math.random() * 200;
    const dx = Math.cos(radians) * thrust;
    const dy = Math.sin(radians) * thrust + 260 + Math.random() * 240;
    particle.style.setProperty("--confetti-dx", `${dx}px`);
    particle.style.setProperty("--confetti-dy", `${dy}px`);

    const rotation = 180 + Math.random() * 540;
    particle.style.setProperty("--confetti-rotate", `${rotation}deg`);

    const lifetime = baseDuration * (0.75 + Math.random() * 0.35);
    particle.style.setProperty("--confetti-duration", `${lifetime}ms`);
    particle.style.animationDelay = `${Math.random() * 120}ms`;

    root.appendChild(particle);
  }

  window.setTimeout(() => {
    root.classList.add("confetti-overlay--fade");
    window.setTimeout(() => {
      root.remove();
    }, 520);
  }, baseDuration + 180);
};

type SparkleOptions = {
  selectors?: string[];
};

const isMatchingTarget = (element: Element | null, selectors: string[]) => {
  if (!element) return false;
  return selectors.some((selector) => (element as HTMLElement).closest(selector));
};

const createSparkleBurst = (x: number, y: number) => {
  const root = document.createElement("div");
  root.className = "sparkle-pop";
  root.style.left = `${x}px`;
  root.style.top = `${y}px`;

  const particles = 8 + Math.floor(Math.random() * 6);
  for (let index = 0; index < particles; index += 1) {
    const spark = document.createElement("span");
    spark.className = "sparkle-pop__particle";
    const angle = (index / particles) * 360 + Math.random() * 25;
    const distance = 45 + Math.random() * 45;
    const color = SPARKLE_COLORS[index % SPARKLE_COLORS.length];
    spark.style.setProperty("--spark-angle", `${angle}deg`);
    spark.style.setProperty("--spark-distance", `${distance}px`);
    spark.style.setProperty("--spark-color", color);
    spark.style.animationDelay = `${Math.random() * 40}ms`;
    root.appendChild(spark);
  }

  document.body.appendChild(root);
  window.requestAnimationFrame(() => root.classList.add("is-active"));
  window.setTimeout(() => {
    root.remove();
  }, 520);
};

export const enableClickSparkles = (options: SparkleOptions = {}) => {
  if (typeof document === "undefined") {
    return () => undefined;
  }
  const selectors = options.selectors && options.selectors.length > 0
    ? options.selectors
    : [...DEFAULT_INTERACTIVE_SELECTORS];

  const handlePointerDown = (event: PointerEvent) => {
    const target = event.target as HTMLElement | null;
    if (!target || !isMatchingTarget(target, selectors)) {
      return;
    }

    const x = event.clientX ?? 0;
    const y = event.clientY ?? 0;
    createSparkleBurst(x, y);
  };

  const listenerOptions: AddEventListenerOptions = { capture: true };
  document.addEventListener("pointerdown", handlePointerDown, listenerOptions);
  return () => {
    document.removeEventListener("pointerdown", handlePointerDown, listenerOptions);
  };
};

type FireworkOptions = {
  bursts?: number;
  colors?: string[];
};

const FIREWORK_COLORS = [
  "#FDE68A",
  "#FBB6CE",
  "#A5B4FC",
  "#6EE7B7",
  "#C4B5FD",
  "#FCA5A5",
];

export const fireFireworks = (options: FireworkOptions = {}) => {
  if (typeof document === "undefined") return;
  const root = document.createElement("div");
  root.className = "fireworks-overlay";
  document.body.appendChild(root);

  const bursts = Math.max(3, options.bursts ?? 5);
  const palette = options.colors && options.colors.length ? options.colors : FIREWORK_COLORS;

  for (let index = 0; index < bursts; index += 1) {
    const firework = document.createElement("div");
    firework.className = "firework";
    const x = 12 + Math.random() * 76;
    const y = 25 + Math.random() * 35;
    firework.style.setProperty("--firework-x", `${x}%`);
    firework.style.setProperty("--firework-y", `${y}%`);
    firework.style.setProperty("--firework-delay", `${index * 120}ms`);
    firework.style.setProperty("--firework-color", palette[index % palette.length]);

    const sparkCount = 12 + Math.floor(Math.random() * 6);
    for (let sparkIndex = 0; sparkIndex < sparkCount; sparkIndex += 1) {
      const spark = document.createElement("span");
      spark.className = "firework__spark";
      const angle = (sparkIndex / sparkCount) * 360;
      const travel = 60 + Math.random() * 80;
      spark.style.setProperty("--spark-angle", `${angle}deg`);
      spark.style.setProperty("--spark-distance", `${travel}px`);
      spark.style.animationDelay = `${Math.random() * 180}ms`;
      firework.appendChild(spark);
    }

    const halo = document.createElement("span");
    halo.className = "firework__halo";
    firework.appendChild(halo);

    root.appendChild(firework);
  }

  window.setTimeout(() => {
    root.classList.add("fireworks-overlay--fade");
    window.setTimeout(() => root.remove(), 600);
  }, 2200);
};

export default fireConfetti;
