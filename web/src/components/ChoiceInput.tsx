import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

/** An editable candidate picker, matching the desktop review's combo box. */
export function ChoiceInput({ label, value, options, onChange, required, hint, error, t }: {
  label: string; value: string; options: string[];
  onChange: (value: string) => void; required: boolean;
  hint?: string; error?: string; t: (key: string) => string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const choose = (answer: string) => { onChange(answer); setOpen(false); };
  return (
    <div className="spec-question" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <label htmlFor={id}>{label}{required && <span className="required-mark">{t("必填")}</span>}</label>
      <div className="choice-input">
        <input id={id} role={options.length ? "combobox" : undefined}
          aria-expanded={options.length ? open : undefined}
          aria-controls={options.length ? `${id}-choices` : undefined}
          aria-autocomplete={options.length ? "list" : undefined}
          aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
          aria-required={required} aria-invalid={!!error}
          aria-describedby={hint || error ? `${id}-hint` : undefined}
          placeholder={options.length ? t("选择候选项或自行填写") : t("请填写")}
          value={value} onChange={(event) => { onChange(event.target.value); setActive(-1); }}
          onClick={() => { setOpen(true); setActive(options.indexOf(value)); }}
          onKeyDown={(event) => {
            if (!options.length) return;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault(); setOpen(true);
              setActive((old) => old < 0 ? (event.key === "ArrowDown" ? 0 : options.length - 1) : (old + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length);
            } else if (event.key === "Enter" && open && active >= 0) {
              event.preventDefault(); choose(options[active]);
            } else if (event.key === "Escape") { setOpen(false); }
          }} />
        {!!options.length && <button type="button" className="choice-toggle"
          aria-label={`${t("候选项")}：${label}`} aria-expanded={open}
          onClick={() => { setOpen(!open); setActive(options.indexOf(value)); }}><ChevronDown size={16} /></button>}
        {open && !!options.length && <div id={`${id}-choices`} role="listbox" aria-label={label} className="choice-options">
          {options.map((option, index) => <div id={`${id}-${index}`} role="option" key={option}
            aria-selected={value === option} className={active === index ? "active" : ""}
            onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option)}>{option}</div>)}
        </div>}
      </div>
      {(hint || error) && <p id={`${id}-hint`} className={error ? "error-text" : "muted"} role={error ? "alert" : undefined}>{error || hint}</p>}
    </div>
  );
}
