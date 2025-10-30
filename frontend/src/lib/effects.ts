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

export default fireConfetti;
