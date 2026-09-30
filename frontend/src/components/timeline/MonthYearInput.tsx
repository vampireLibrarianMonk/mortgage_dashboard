interface Props {
  // Stored value is "YYYY-MM" (or "" when empty/unset).
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  // Lower bound as "YYYY-MM" — the control won't emit a value earlier than this
  // (used so an end date can't precede its start).
  min?: string;
  title?: string;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function parse(value: string): { year: string; month: string } {
  const m = /^(\d{4})-(\d{2})$/.exec(value);
  if (!m) return { year: "", month: "" };
  return { year: m[1], month: m[2] };
}

function compose(year: string, month: string): string {
  // Only a complete year+month makes a valid stored value; otherwise empty.
  if (!/^\d{4}$/.test(year) || !month) return "";
  return `${year}-${month}`;
}

/**
 * Month + year entry that is fully keyboard-enterable and has no native calendar
 * icon (which truncated the field and blocked typing). A month <select> (type to
 * jump, arrows to change) plus a year <input type="number"> (type the year). The
 * value round-trips as "YYYY-MM" so nothing downstream changes.
 *
 * Chosen over the native <input type="month"> (no manual entry, icon overflow) and
 * over a free-text parser (ambiguous input) — this is unambiguous, dependency-free,
 * and expands to fill its column.
 */
export default function MonthYearInput({ value, onChange, disabled, min, title }: Props) {
  const { year, month } = parse(value);

  const emit = (nextYear: string, nextMonth: string) => {
    let composed = compose(nextYear, nextMonth);
    if (composed && min && composed < min) composed = min;
    onChange(composed);
  };

  return (
    <div className="tl-monthyear" title={title}>
      <select
        className="tl-my-month"
        value={month}
        disabled={disabled}
        aria-label="Month"
        onChange={(e) => emit(year, e.target.value)}
      >
        <option value="">Mon</option>
        {MONTHS.map((label, idx) => {
          const mm = String(idx + 1).padStart(2, "0");
          return (
            <option key={mm} value={mm}>
              {label}
            </option>
          );
        })}
      </select>
      <input
        className="tl-my-year"
        type="number"
        inputMode="numeric"
        placeholder="Year"
        min={1900}
        max={2200}
        value={year}
        disabled={disabled}
        aria-label="Year"
        onChange={(e) => {
          const y = e.target.value.replace(/[^\d]/g, "").slice(0, 4);
          emit(y, month);
        }}
      />
    </div>
  );
}
