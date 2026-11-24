import * as React from "react"
import { Check, ChevronDown } from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

export interface SelectOption {
  value: string
  label: React.ReactNode
  /** 选项的补充说明；触发器只显示 label，避免长描述把控件撑坏 */
  description?: string
  disabled?: boolean
}

interface SelectMenuProps {
  value?: string
  options: SelectOption[]
  onChange: (value: string) => void
  placeholder?: string
  ariaLabel: string
  title?: string
  className?: string
  disabled?: boolean
  menuMinWidth?: number
}

/** 产品内统一的单选下拉。原生 select 的系统弹层无法跟随主题，这里用 listbox。 */
export function SelectMenu({
  value, options, onChange, placeholder = "—", ariaLabel, title, className, disabled,
  menuMinWidth,
}: SelectMenuProps) {
  const id = React.useId()
  const [open, setOpen] = React.useState(false)
  const [active, setActive] = React.useState(0)
  const [menuWidth, setMenuWidth] = React.useState(120)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const listRef = React.useRef<HTMLDivElement>(null)
  const selectedIndex = options.findIndex((option) => option.value === value)
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined

  React.useEffect(() => {
    if (!open) return
    setActive(selectedIndex >= 0 ? selectedIndex : 0)
    const timer = window.setTimeout(() => listRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open, selectedIndex])

  React.useEffect(() => {
    if (!open) return
    listRef.current
      ?.querySelector<HTMLElement>(`#${CSS.escape(`${id}-option-${active}`)}`)
      ?.scrollIntoView?.({ block: "nearest" })
  }, [active, id, open])

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setMenuWidth(Math.max(
        menuMinWidth ?? 120,
        triggerRef.current?.getBoundingClientRect().width ?? 0,
      ))
    }
    setOpen(next)
  }

  const pick = (option: SelectOption) => {
    if (option.disabled) return
    onChange(option.value)
    setOpen(false)
  }

  const onListKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!options.length) return
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActive((index) => (index + 1) % options.length)
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActive((index) => (index - 1 + options.length) % options.length)
    } else if (event.key === "Home") {
      event.preventDefault()
      setActive(0)
    } else if (event.key === "End") {
      event.preventDefault()
      setActive(options.length - 1)
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      pick(options[active])
    } else if (event.key === "Escape") {
      event.preventDefault()
      setOpen(false)
    } else if (event.key === "Tab") {
      setOpen(false)
    }
  }

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <PopoverPrimitive.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          className={cn("ed ed--sel sel__trigger", className)}
          aria-label={ariaLabel}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={`${id}-listbox`}
          title={selected?.description ?? title}
          disabled={disabled}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault()
              handleOpenChange(true)
            }
          }}
        >
          <span className="sel__value">{selected?.label ?? placeholder}</span>
          <ChevronDown className="sel__chevron" size={14} aria-hidden />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={5}
          className="sel__content"
          style={{ minWidth: menuWidth }}
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            window.setTimeout(() => listRef.current?.focus(), 0)
          }}
        >
          <div
            ref={listRef}
            id={`${id}-listbox`}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            aria-activedescendant={options[active] ? `${id}-option-${active}` : undefined}
            className="sel__viewport"
            onKeyDown={onListKeyDown}
          >
            {options.map((option, index) => (
              <button
                key={option.value || "__empty__"}
                id={`${id}-option-${index}`}
                type="button"
                role="option"
                aria-selected={option.value === (value ?? "")}
                disabled={option.disabled}
                tabIndex={-1}
                className={cn("sel__item", index === active && "is-active")}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(option)}
              >
                <span className="sel__itemtext">
                  <span className="sel__itemlabel">{option.label}</span>
                  {option.description && (
                    <span className="sel__itemdesc">{option.description}</span>
                  )}
                </span>
                {option.value === (value ?? "") && (
                  <span className="sel__check">
                    <Check size={14} aria-hidden />
                  </span>
                )}
              </button>
            ))}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
