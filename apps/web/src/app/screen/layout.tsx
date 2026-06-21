export default function ScreenLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-x-0 bottom-0 top-[58px] z-10 overflow-hidden bg-canvas">
      <div className="mx-auto flex h-full w-full max-w-content flex-col overflow-hidden px-6 lg:px-8">
        <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
