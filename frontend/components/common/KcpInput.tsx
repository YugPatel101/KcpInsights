import { useId } from "react";

interface KcpInputProps extends React.ComponentProps<"input"> {
  label: string;
  error?: string;
}

export default function KcpInput({ label, error, type = "text", className, ...props }: KcpInputProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-medium text-ink-2">
        {label}
      </label>

      <input
        id={id}
        type={type}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
        className={`w-full rounded-xl border bg-surface px-4 py-3 text-ink outline-none transition-all duration-300 placeholder:text-ink-3 focus:bg-surface ${
          error ? "border-neg/60 focus:border-neg" : "border-line focus:border-brand"
        } ${className ?? ""}`}
        {...props}
      />
      {error && (
        <p id={`${id}-err`} className="mt-1.5 text-xs text-neg-ink">
          {error}
        </p>
      )}
    </div>
  );
}
