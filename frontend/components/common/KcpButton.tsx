import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface KcpButtonProps extends React.ComponentProps<typeof Button> {}

export default function KcpButton({
  className,
  children,
  ...props
}: KcpButtonProps) {
  return (
    <Button
      className={cn(
        "h-12 min-w-40 rounded-xl border border-slate-700 bg-transparent px-8 text-[15px] font-semibold text-white transition-all duration-300 hover:border-white hover:bg-white hover:text-black",
        className
      )}
      {...props}
    >
      {children}
    </Button>
  );
}