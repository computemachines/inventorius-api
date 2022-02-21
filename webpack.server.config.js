const webpack = require("webpack");
const path = require("path");
const MiniCssExtractPlugin = require("mini-css-extract-plugin")

const isDevelopment = process.env.NODE_ENV !== 'production';

module.exports = {
    mode: isDevelopment ? "development" : "production",
    devtool: isDevelopment && "inline-source-map",
    target: "node",
    entry: {
        server: "./src/server/entry",
    },
    resolve: {
        extensions: [".js", ".ts", ".tsx"],
    },
    output: {
        filename: "[name].bundle.js",
        path: path.join(__dirname, "dist"),
        library: "app",
        libraryTarget: "commonjs2",
    },
    module: {
        rules: [
            {
                test: /\.tsx?$/,
                exclude: /node_modules/,
                loader: "ts-loader",
            },
            {
                test: /\.css$/,
                use: [MiniCssExtractPlugin.loader, "css-loader"],
            },
        ]
    },
    plugins: [
        new MiniCssExtractPlugin({
            filename: "/assets/main.css",
        })
    ],
}