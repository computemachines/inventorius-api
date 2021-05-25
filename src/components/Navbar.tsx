import * as React from "react";
import { Link } from "react-router-dom";
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
        setActive(false);
      }}
      onFocus={() => setActive(true)}
      className={`navbar screen-reader${isActive ? "screen-reader-show" : ""}`}
    >
      <Link className="navlink" to="/">
        Home
      </Link>
      <NavlinkDropdown text="New">
        <Link className="navlink" to="/new/bin">
          New Bin
        </Link>
        <Link className="navlink" to="/new/sku">
          New SKU
        </Link>
        <Link className="navlink" to="/new/batch">
          New Batch
        </Link>
      </NavlinkDropdown>
      <Link className="navlink" to="/move">
        Move
      </Link>
      <Link className="navlink" to="/receive">
        Receive
      </Link>
      <Link className="navlink" to="/search">
        Search
      </Link>
    </nav>
  );
}

export default Navbar;
