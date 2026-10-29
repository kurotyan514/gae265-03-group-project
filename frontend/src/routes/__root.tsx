import { createRootRoute, Outlet } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: () => (
    <div className="mx-auto min-h-dvh max-w-5xl p-6">
      <Outlet />
    </div>
  ),
});
