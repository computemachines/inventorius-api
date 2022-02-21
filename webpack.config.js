const path = require("path");
const ReactRefreshWebpackPlugin = require("@pmmmwh/react-refresh-webpack-plugin");
const ForkTsCheckerWebpackPlugin = require("fork-ts-checker-webpack-plugin");
// const HtmlWebpackPlugin = require('html-webpack-plugin');
const ReactRefreshTypeScript = require("react-refresh-typescript").default;

const isDevelopment = process.env.NODE_ENV !== "production";
const nohot = process.env.NO_HOT === "true"; // only used in ReactRefreshWebpackPlugin removal
isDevelopment && console.log("DEVELOPMENT MODE");
nohot && console.log("DISABLED ReactRefreshWebpackPlugin");

// const SentryCliPlugin = require('@sentry/webpack-plugin');

module.exports = {
  mode: isDevelopment ? "development" : "production",
  devtool: isDevelopment && "inline-source-map",
  entry: {
    client: "./src/client/entry.tsx",
  },
  output: {
    path: path.join(__dirname, "dist/assets"),
    filename: "[name].bundle.js",
  },
  devServer: {
    historyApiFallback: true,
    port: 8080,
    hot: "only",
    proxy: {
      "/api/": "http://localhost:8081/",
    },
  },
  module: {
    rules: [
      {
        test: /\.js?$/,
        enforce: "pre",
        use: "source-map-loader",
      },
      {
        test: /\.tsx?$/,
        include: path.join(__dirname, "src"),
        use: [
          {
            loader: "ts-loader",
            options: {
              transpileOnly: true,
              getCustomTransformers: () => ({
                before:
                  isDevelopment && !nohot ? [ReactRefreshTypeScript()] : [],
              }),
            },
          },
        ].filter(Boolean),
      },
      {
        test: /\.css$/,
        use: ["style-loader", "css-loader"],
      },
      {
        test: /\.svg$/,
        use: [{ loader: "@svgr/webpack", options: { typescript: true } }],
      },
    ],
  },
  plugins: [
    isDevelopment && !nohot && new ReactRefreshWebpackPlugin(), //do not include in nonhot client builds. results in cryptic error "internal/crypto/hash.js:69 TypeError ERR_INVALID_ARG_TYPE"
    new ForkTsCheckerWebpackPlugin(),
  ].filter(Boolean),
  resolve: {
    extensions: [".js", ".ts", ".tsx", ".svg"],
  },
};
