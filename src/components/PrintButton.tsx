import * as React from "react";

import "../styles/PrintButton.css";

function PrintButton({ value }: { value: string }) {
  return <button className="form-print-button">Print</button>;
}

export default PrintButton;
