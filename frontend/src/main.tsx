import "@mantine/core/styles.css";
import "./theme/global.css";

import React from "react";
import ReactDOM from "react-dom/client";
import { AppProviders } from "@/app-providers";
import App from "@/app/App";
import "@/services/axiosClient";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </React.StrictMode>,
);
