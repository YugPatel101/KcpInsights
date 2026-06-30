interface KcpInputProps {
  label: string;
  type?: string;
  placeholder?: string;
}

export default function KcpInput({
  label,
  type = "text",
  placeholder,
}: KcpInputProps) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-300">
        {label}
      </label>

      <input
        type={type}
        placeholder={placeholder}
        className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none transition-all duration-300 placeholder:text-slate-500 focus:border-blue-400 focus:bg-black/50"
      />
    </div>
  );
}