import * as React from "react";
import { useState } from "react";

import AlertContext from "./AlertContext";
import ErrorBoundary from "./ErrorBoundary";
import Hamburger from "./Hamburger";

import "normalize.css";
import "../styles/accessibility.css";
import "../styles/App.css";
import Navbar from "./Navbar";

function App() {
  const [alert, setAlert] = useState(null);
  const [dropdownIsActive, setDropdownIsActive] = useState(false);

  return (
    <div className="app-wrapper">
      <Hamburger isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <Navbar isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <div className="main-container">
        <div className="main-content" id="main">
          <ErrorBoundary>
            <AlertContext.Provider value={[alert, setAlert]}>
              <div className="main-alert">{alert}</div>
            </AlertContext.Provider>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}

export default App;
