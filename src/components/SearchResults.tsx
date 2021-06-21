import * as React from "react";
import { useEffect } from "react";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/SearchResults.css";
import "../styles/infoPanel.css";

// TODO: push current live query to location hsitory when navigating away or after ~10 seconds of no change
function SearchResults({ query }: { query: string }) {
  const { data, frontloadMeta, setData } = useFrontload(
    "searchresults-component",
    async ({ api }: FrontloadContext) => {
      console.log("frontload fetching");
      return {
        api: api,
        searchResults: await api.getSearchResults({ query }),
      };
    }
  );

  // Update search results when query changes.
  // Do not update if resolving old promise.
  useEffect(() => {
    if (!frontloadMeta.done) return;

    let isCancelled = false;

    data.api.getSearchResults({ query }).then((newSearchResults) => {
      if (!isCancelled)
        setData(({ api }) => ({ api, searchResults: newSearchResults }));
    });
    return () => {
      isCancelled = true;
    };
  }, [query]);

  if (frontloadMeta.pending) return <div>Loading ...</div>;
  if (frontloadMeta.error || data.searchResults.kind == "problem")
    return <div>API error!</div>;

  const searchResultsState = data.searchResults.state;
  return (
    <div className="info-item">
      <div className="info-item-title">
        {searchResultsState.total_num_results} Results
      </div>
      {searchResultsState.results.map((i, result) => null)}
    </div>
  );
}
export default SearchResults;
