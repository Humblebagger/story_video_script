import * as React from "react"
import { cn } from "@/lib/utils"

type NumberFieldProps = Omit<React.ComponentProps<"input">, "type">

/** 数字输入：文本语义 + 数字键盘，不出现浏览器步进箭头；解析与校验交给调用方。 */
export function NumberField({ className, inputMode = "decimal", ...props }: NumberFieldProps) {
  return (
    <input
      {...props}
      type="text"
      inputMode={inputMode}
      className={cn("ui-number", className)}
    />
  )
}
