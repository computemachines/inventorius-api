import * as React from "react";
import { useState } from "react";

import AlertContext from "./AlertContext";
import ErrorBoundary from "./ErrorBoundary";
import HamburgerBar from "./HamburgerBar";

import "normalize.css";

export default () => {
  const [alert, setAlert] = useState(null);

  return (
    <div className="app-wrapper">
      <HamburgerBar />
      <div className="main-container">
        <div className="main-content">
          <ErrorBoundary>
            <AlertContext.Provider value={[alert, setAlert]}>
              <div className="main-alert">{alert}</div>
            </AlertContext.Provider>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
};
