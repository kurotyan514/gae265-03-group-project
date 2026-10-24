import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { routeTree } from "./routeTree.gen";
import "./styles.css";

// 元件都放在 routes/：main.tsx 不是 Fast Refresh boundary，改這裡會讓 Vite HMR 失效到重啟 dev server
const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

async function start() {
  // dynamic import 放在判斷裡：VITE_MOCK 不是 true 時 build 會整段拿掉，產物不含 MSW
  if (import.meta.env.VITE_MOCK === "true") {
    const { startMockWorker } = await import("./mocks/browser");
    await startMockWorker();
  }

  const rootElement = document.getElementById("root");
  if (!rootElement) throw new Error("找不到 #root");
  createRoot(rootElement).render(
    <StrictMode>
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}

void start();
