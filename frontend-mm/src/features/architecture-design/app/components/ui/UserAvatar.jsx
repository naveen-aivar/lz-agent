// The signed-in person as their initials in the brand blue (sign-in does not give a photo). "Arun Sharma" is "AS". size: sm | md | lg
export const initialsOf = (name) => {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? Array.from(words[words.length - 1])[0] ?? "" : "";
  return `${first}${last}`.toUpperCase();
};

export default function UserAvatar({ name, size = "md" }) {
  return <span aria-hidden className={`avatar avatar-${size}`}>{initialsOf(name)}</span>;
}
