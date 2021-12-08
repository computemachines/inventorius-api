import * as React from "react";
import { Link } from "react-router-dom";

import "../styles/Pager.css";

export function Pager({
  currentPage: page,
  numPages,
  linkHref,
  scrollToTop = true,
}) {
  let onClick;
  const shownPageLinks = [page - 2, page - 1, page, page + 1, page + 2].filter(
    (p) => p >= 1 && p <= numPages
  );

  if (!numPages) return null;

  if (scrollToTop) {
    onClick = () => window.scrollTo(0, 0);
  } else {
    onClick = () => {};
  }

  return (
    <div className="pager">
      <span className="pager--note">Page:</span>
      {page - 2 > 1 ? (
        <Link onClick={onClick} to={linkHref + 1} className="pager--page-link">
          |&lt;
        </Link>
      ) : null}
      {page !== 1 ? (
        <Link
          onClick={onClick}
          to={linkHref + (page - 1)}
          className="pager--page-link"
        >
          &lt;
        </Link>
      ) : null}
      {page - 2 > 1 ? "..." : null}
      {shownPageLinks.map((p) => (
        <Link
          onClick={onClick}
          to={linkHref + p}
          key={p}
          className={`pager--page-link ${
            p == page ? "pager--page-link__active" : ""
          }`}
        >
          {p}
        </Link>
      ))}
      {page + 2 < numPages ? "..." : null}
      {numPages > page ? (
        <Link
          onClick={onClick}
          to={linkHref + (page + 1)}
          className="pager--page-link"
        >
          &gt;
        </Link>
      ) : null}
      {page + 2 < numPages ? (
        <Link
          onClick={onClick}
          to={linkHref + numPages}
          className="pager--page-link"
        >
          &gt;|
        </Link>
      ) : null}
    </div>
  );
}
