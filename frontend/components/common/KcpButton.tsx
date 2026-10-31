import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type KcpButtonProps = React.ComponentProps<typeof Button>;

export default function KcpButton({ className, children, ...props }: KcpButtonProps) {
  return (
    <Button
      className={cn(
        "h-10 rounded-md border border-transparent bg-brand px-5 text-sm font-semibold text-white transition hover:bg-brand/85",
        className,
      )}
      {...props}
    >
      {children}
    </Button>
  );
}
