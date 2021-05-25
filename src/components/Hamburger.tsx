import * as React from "react";
import { useState } from "react";

import "hamburgers/dist/hamburgers.css";
import "../styles/HamburgerBar.css"; // must load after hamburgers.css

function Hamburger({ isActive, setActive }): JSX.Element {
  return (
    <div className="top-bar">
      <div className="logo" />
      <h2>Inventory App</h2>
      <button
        className={`hamburger hamburger--squeeze ${
          isActive ? "is-active" : ""
        }`}
        type="button"
        aria-label="Menu"
        aria-controls="navigation"
        onClick={() => setActive(!isActive)}
        onBlur={() => setActive(false)}
        onFocus={() => setActive(true)}
      >
        <span className="hamburger-label">Menu</span>
        <span className="hamburger-box">
          <span className="hamburger-inner" />
        </span>
      </button>
    </div>
  );
}

export default Hamburger;
