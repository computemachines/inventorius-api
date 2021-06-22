import * as React from "react";
import { useEffect } from "react";
import { useHistory } from "react-router";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";
import {
  BinState,
  isBatchState,
  isBinState,
  isSkuState,
  SearchResult,
  SearchResults as APISearchResults,
  SkuState,
} from "../api-client/data-models";

import "../styles/SearchResults.css";
import "../styles/infoPanel.css";
import { parse, stringifyUrl } from "query-string";
import DataTable, { HeaderSpec } from "./DataTable";

function resultToType(result: SearchResult): "SKU" | "BATCH" | "BIN" {
  if (isBinState(result)) return "BIN";
  if (isSkuState(result)) return "SKU";
  if (isBatchState(result)) return "BATCH";
}

function SearchResultsTable({
  searchResults,
}: {
  searchResults: APISearchResults;
}) {
  const searchResultToDataRow = (result: SearchResult) => ({
    Identifier: result.id,
    Name: !isBinState(result) ? result.name : "",
    Type: resultToType(result),
  });
  const tabularData = searchResults.state.results.map(searchResultToDataRow);
  return (
    <DataTable
      headers={["Identifier", "Name", "Type"]}
      data={tabularData}
      headerSpecs={{
        Identifier: new HeaderSpec(".ItemLabel"),
        Name: new HeaderSpec(".truncated", {
          kind: "min-max-width",
          minWidth: 100,
          maxWidth: "1fr",
        }),
        // Quantity: new HeaderSpec(".numeric"),
      }}
    />
  );
}

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
  const history = useHistory();

  // Update search results when query changes.
  // Do not update if not resolving most recent promise.
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

  // save query to history if stay on page for 10s
  useEffect(() => {
    const timer = setTimeout(() => {
      history.push(stringifyUrl({ url: "/search", query: { query } }));
    }, 10000);
    return () => clearTimeout(timer);
  });

  if (frontloadMeta.pending) return <div>Loading ...</div>;
  if (frontloadMeta.error || data.searchResults.kind == "problem")
    return <div>API error!</div>;

  return (
    <div className="info-item">
      <div className="info-item-title">
        {data.searchResults.state.total_num_results} Results
      </div>
      <SearchResultsTable searchResults={data.searchResults} />
    </div>
  );
}
export default SearchResults;
