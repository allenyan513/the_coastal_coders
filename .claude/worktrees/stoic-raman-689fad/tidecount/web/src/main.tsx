import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Compare } from "./Compare";
import { Library } from "./Library";
import { School } from "./School";
import { SummaryPage } from "./Summary";
import { Tracks } from "./Tracks";
import { Workspace } from "./Workspace";

function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <header className="topbar">
          <Link to="/" className="brand">TideCount</Link>
          <span className="spacer" />
          <span className="meta">Local · nothing leaves this PC</span>
        </header>
        <main className="page">
          <Routes>
            <Route path="/" element={<Library />} />
            <Route path="/videos/:id" element={<Workspace />} />
            <Route path="/videos/:id/tracks" element={<Tracks />} />
            <Route path="/videos/:id/compare" element={<Compare />} />
            <Route path="/videos/:id/school" element={<School />} />
            <Route path="/videos/:id/summary" element={<SummaryPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
