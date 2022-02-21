import * as React from "react";
import { Link } from "react-router-dom";

import "../styles/ItemLabel.css";

const ItemLabel = ({
  link = true,
  label,
  url,
  inline = true,
  onClick,
}: {
  link?: boolean;
  label?: string;
  url?: string;
  inline?: boolean;
  onClick?: React.MouseEventHandler<HTMLAnchorElement>;
}) => {
  if (url) {
    const match = url.match(/^(\/api)?\/(?<unit>bin|sku|batch)\/(?<label>.+)/);
    if (!match) return <span>{url}</span>;
    label = match.groups.label;
  }
  const match = label.match(
    /^(?<prefix>BIN|SKU|BAT)(?<leadingZeroes>0*)(?<number>\d+)$/
  );
  if (!match) return <span>{label}</span>;

  const { prefix, number } = match.groups;
  const leadingZeros = match.groups.leadingZeroes || "";

  let unitUrl;
  switch (prefix) {
  case "BIN":
    unitUrl = "/bin/";
    break;
  case "SKU":
    unitUrl = "/sku/";
    break;
  case "BAT":
    unitUrl = "/batch/";
    break;
  }

  if (link) {
    return (
      <Link
        to={unitUrl + label}
        className={`item-label ${inline ? "item-label--inline" : ""}`}
        onClick={onClick}
      >
        {prefix}
        <span className="item-label--zeroes">{leadingZeros}</span>
        <span className="item-label--code">{number}</span>
      </Link>
    );
  } else {
    return (
      <div className={`item-label ${inline ? "item-label--inline" : ""}`}>
        {prefix}
        <span className="item-label--zeroes">{leadingZeros}</span>
        <span className="item-label--code">{number}</span>
      </div>
    );
  }
};

export default ItemLabel;
