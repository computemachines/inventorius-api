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
import NewBin from "./NewBin";

const FourOhFour = () => (
  <Status code={404}>
    <div>
      <h1>404 - Not found</h1>
    </div>
  </Status>
);

const Alert = ({ onClose, children }) =>
  children ? (
    <div className="main-alert" id="#alert">
      <button role="close" className="alert-close-button" onClick={onClose}>
        X
      </button>
      {children}
    </div>
  ) : null;

function App() {
  const [alertContent, setAlertContent] = useState(null);
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
            <AlertContext.Provider value={{ setAlertContent }}>
              <Alert onClose={() => setAlertContent(null)}>
                {alertContent}
              </Alert>
              <Switch>
                <Route exact path="/" component={Home} />
                <Route path="/new/bin" component={NewBin} />
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
