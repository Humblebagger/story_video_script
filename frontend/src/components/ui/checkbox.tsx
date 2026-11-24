import type { ComponentProps } from "react"
import { cn } from "@/lib/utils"

/** 保留原生 checkbox 的语义与事件，只替换系统外观，方便所有旧表单原地升级。 */
export function Checkbox({
  className,
  ...props
}: Omit<ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      {...props}
      className={cn("ui-check", className)}
    />
  )
}
