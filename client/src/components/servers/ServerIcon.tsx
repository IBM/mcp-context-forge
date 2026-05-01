import { useMemo, memo } from "react";

enum ServerIconColor {
  Red = "bg-red-500",
  Orange = "bg-orange-500",
  Amber = "bg-amber-500",
  Yellow = "bg-yellow-500",
  Lime = "bg-lime-500",
  Green = "bg-green-500",
  Emerald = "bg-emerald-500",
  Teal = "bg-teal-500",
  Cyan = "bg-cyan-500",
  Sky = "bg-sky-500",
  Blue = "bg-blue-500",
  Indigo = "bg-indigo-500",
  Violet = "bg-violet-500",
  Purple = "bg-purple-500",
  Fuchsia = "bg-fuchsia-500",
  Pink = "bg-pink-500",
}

const COLORS = Object.values(ServerIconColor);

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash = hash & hash;
  }
  return Math.abs(hash);
}

interface ServerIconProps {
  name: string;
  size?: "sm" | "md" | "lg";
}

export const ServerIcon = memo(function ServerIcon({ name, size = "md" }: ServerIconProps) {
  const colorClass = useMemo(() => {
    const hash = hashString(name);
    return COLORS[hash % COLORS.length];
  }, [name]);

  const sizeClasses = {
    sm: "w-6 h-6 text-xs",
    md: "w-8 h-8 text-sm",
    lg: "w-10 h-10 text-base",
  };

  const initial = name.charAt(0).toUpperCase();

  return (
    <div
      className={`${colorClass} ${sizeClasses[size]} rounded-md flex items-center justify-center text-white font-semibold`}
    >
      {initial}
    </div>
  );
});

ServerIcon.displayName = "ServerIcon";
