import { useId } from "react";

interface KcpInputProps extends React.ComponentProps<"input"> {
  label: string;
  error?: string;
}

export default function KcpInput({ label, error, type = "text", className, ...props }: KcpInputProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-medium text-slate-300">
        {label}
      </label>

      <input
        id={id}
        type={type}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
        className={`w-full rounded-xl border bg-black/30 px-4 py-3 text-white outline-none transition-all duration-300 placeholder:text-slate-500 focus:bg-black/50 ${
          error ? "border-rose-500/60 focus:border-rose-400" : "border-white/10 focus:border-blue-400"
        } ${className ?? ""}`}
        {...props}
      />
      {error && (
        <p id={`${id}-err`} className="mt-1.5 text-xs text-rose-300">
          {error}
        </p>
      )}
    </div>
  );
}
