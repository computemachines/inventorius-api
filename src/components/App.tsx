import * as React from "react";
import { useState } from "react";
import { Route, Switch } from "react-router-dom";

import "normalize.css";
import "../styles/accessibility.css";
import "../styles/App.css";

import AlertContext from "./AlertContext";
import ErrorBoundary from "./ErrorBoundary";
import Topbar from "./Topbar";
import Navbar from "./Navbar";
import Home from "./Home";
import Status from "./Status";

const FourOhFour = () => (
  <Status code={404}>
    <div>
      <h1>404 - Not found</h1>
    </div>
  </Status>
);

function App() {
  const [alert, setAlert] = useState(null);
  const [dropdownIsActive, setDropdownIsActive] = useState(false);

  // const setDropdownIsActive = (state: boolean) => {
  //   console.log("setDropdownIsActive(" + state + ")");
  //   _setDropdownIsActive(state);
  // };

  return (
    <div className="app-wrapper">
      <Topbar isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <Navbar isActive={dropdownIsActive} setActive={setDropdownIsActive} />
      <div className="main-container">
        <div className="main-content" id="main">
          <ErrorBoundary>
            <AlertContext.Provider value={[alert, setAlert]}>
              <div className="main-alert" id="#alert">
                {alert}
              </div>
              <Switch>
                <Route exact path="/">
                  <Home />
                </Route>
                <Route component={FourOhFour} />
              </Switch>
            </AlertContext.Provider>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}

export default App;
