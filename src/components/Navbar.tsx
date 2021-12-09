import * as React from "react";
import { NavLink } from "react-router-dom";
import NavlinkDropdown from "./NavlinkDropdown";

import "../styles/Navbar.css";

function Navbar({
  isActive,
  setActive,
}: {
  isActive: boolean;
  setActive: (s: boolean) => void;
}) {
  return (
    <nav
      onBlur={() => {
        // console.log("nav onblur");
        // setActive(false);
      }}
      onFocus={() => {
        // console.log("nav onFocus");
        setActive(true);
      }}
      onClick={() => {
        // console.log("nav onClick");
        setActive(false);
      }}
      className={`navbar screen-reader ${isActive ? "screen-reader-show" : ""}`}
    >
      <NavLink className="navlink" to="/">
        Home
      </NavLink>
      <NavlinkDropdown text="New">
        <NavLink className="navlink" to="/new/bin">
          New Bin
        </NavLink>
        <NavLink className="navlink" to="/new/sku">
          New SKU
        </NavLink>
        <NavLink className="navlink" to="/new/batch">
          New Batch
        </NavLink>
      </NavlinkDropdown>
      <NavLink className="navlink" to="/move">
        Move
      </NavLink>
      <NavLink className="navlink" to="/receive">
        Receive
      </NavLink>
      <NavLink className="navlink" to="/search">
        Search
      </NavLink>
    </nav>
  );
}

export default Navbar;
