import * as React from "react";
import { generatePath } from "react-router-dom";

import "../styles/PrintButton.css";

/**
 * Print Label Button Component
 *
 * @category Components
 * @param props
 * @param {string} props.value - The text to be printed as a label.
 * @returns {ReactNode}
 */
function PrintButton({ value }: { value: string }) {
  return (
    <button
      className="form-print-button"
      onClick={(e) => {
        e.preventDefault();

        fetch(`http://localhost:8899/print/${value}`);
      }}
    >
      Print
    </button>
  );
}

export default PrintButton;
