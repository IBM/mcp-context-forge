import { useMemo, memo } from "react";
import { MCPIcon } from "@/components/icons/MCPIcon";

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

  const wrapperSizeClasses = {
    sm: "h-5 w-5 rounded-[4px]",
    md: "h-6 w-6 rounded-[5px]",
    lg: "h-8 w-8 rounded-md",
  };

  const iconSizeClasses = {
    sm: "h-3 w-3 text-black",
    md: "h-3.5 w-3.5 text-black",
    lg: "h-4 w-4 text-black",
  };

  return (
    <div
      className={`${colorClass} ${wrapperSizeClasses[size]} flex shrink-0 items-center justify-center`}
      aria-label={`${name} icon`}
    >
      <MCPIcon className={iconSizeClasses[size]} />
    </div>
  );
});

ServerIcon.displayName = "ServerIcon";
