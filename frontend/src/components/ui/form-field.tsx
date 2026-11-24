import * as React from "react"
import { CircleAlert, Info } from "lucide-react"
import { useI18n } from "@/i18n/core"
import { cn } from "@/lib/utils"

export function FieldHint({ id, children, className }: {
  id?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <p id={id} className={cn("ui-field__hint", className)}>
      {children}
    </p>
  )
}

type FormFieldProps = {
  label?: React.ReactNode
  id?: string
  hint?: React.ReactNode
  error?: React.ReactNode
  required?: boolean
  optional?: boolean
  requiredText?: string
  optionalText?: string
  /** 让外层成为 label（兼容需要 label 包住 input 的旧表单与测试） */
  asLabel?: boolean
  className?: string
  children: React.ReactNode
}

/** 统一字段：标签、必填/可选、说明与错误都走同一套排版和错误色。 */
export function FormField({
  label, id, hint, error, required, optional, requiredText, optionalText, asLabel,
  className, children,
}: FormFieldProps) {
  const { t } = useI18n()
  const autoId = React.useId()
  const fieldId = id ?? autoId
  const hintId = hint ? `${fieldId}-hint` : undefined
  const errorId = error ? `${fieldId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined
  const child = React.isValidElement(children)
    ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
        id: (children.props as { id?: string }).id ?? fieldId,
        "aria-describedby": (children.props as { "aria-describedby"?: string })["aria-describedby"] ?? describedBy,
        "aria-invalid": error ? true : (children.props as { "aria-invalid"?: boolean })["aria-invalid"],
      })
    : children
  const Wrapper = asLabel ? "label" : "div"
  const labelBody = label && (
    <>
      <span>{label}</span>
      {required && <em className="ui-field__need">{requiredText ?? t("common.required")}</em>}
      {optional && <em className="ui-field__optional">{optionalText ?? t("common.optional")}</em>}
    </>
  )
  return (
    <Wrapper className={cn("ui-field", error && "is-invalid", className)}>
      {label && (asLabel
        ? <span className="ui-field__label">{labelBody}</span>
        : <label className="ui-field__label" htmlFor={fieldId}>{labelBody}</label>)}
      {child}
      {hint && <FieldHint id={hintId}>{hint}</FieldHint>}
      {error && (
        <p id={errorId} role="alert" className="ui-field__error">
          <CircleAlert aria-hidden />
          <span>{error}</span>
        </p>
      )}
    </Wrapper>
  )
}

type InlineAlertProps = {
  tone?: "info" | "warning" | "error" | "success"
  title?: React.ReactNode
  children: React.ReactNode
  action?: React.ReactNode
  className?: string
  testId?: string
}

const ALERT_ICON = {
  info: Info,
  warning: CircleAlert,
  error: CircleAlert,
  success: Info,
} as const

/** 页面内的提示卡：错误/警告用 role=alert，其余用 status；动作放右侧。 */
export function InlineAlert({ tone = "info", title, children, action, className, testId }: InlineAlertProps) {
  const Icon = ALERT_ICON[tone]
  return (
    <div
      role={tone === "warning" || tone === "error" ? "alert" : "status"}
      data-tone={tone}
      data-testid={testId}
      className={cn("ui-alert", className)}
    >
      <Icon className="ui-alert__icon" aria-hidden />
      <div className="ui-alert__copy">
        {title && <p className="ui-alert__title">{title}</p>}
        <div className="ui-alert__body">{children}</div>
      </div>
      {action && <div className="ui-alert__action">{action}</div>}
    </div>
  )
}
