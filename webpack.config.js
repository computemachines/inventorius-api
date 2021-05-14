const path = require('path');
const ReactRefreshWebpackPlugin = require('@pmmmwh/react-refresh-webpack-plugin');
const ForkTsCheckerWebpackPlugin = require('fork-ts-checker-webpack-plugin');
// const HtmlWebpackPlugin = require('html-webpack-plugin');
const ReactRefreshTypeScript = require('react-refresh-typescript').default;

const isDevelopment = process.env.NODE_ENV !== 'production';

module.exports = {
    mode: isDevelopment ? 'development' : 'production',
    devtool: isDevelopment && "inline-source-map",
    entry: {
        main: './src/client/entry.tsx',
    },
    devServer: {
        overlay: true,
        historyApiFallback: true,
        port: 8080,
        hotOnly: true
    },
    module: {
        rules: [
            {
                test: /\.js$/,
                enforce: "pre",
                use: "source-map-loader",
            },
            {
                test: /\.tsx?$/,
                include: path.join(__dirname, 'src'),
                use: [
                    {
                        loader: 'ts-loader',
                        options: {
                            transpileOnly: true,
                            getCustomTransformers: () => ({
                                before: isDevelopment ? [ReactRefreshTypeScript()] : [],
                            }),
                        },
                    },
                ].filter(Boolean),
            },
            {
                test: /\.css$/,
                use: ["style-loader", "css-loader"],
            },
        ],
    },
    plugins: [
        isDevelopment && new ReactRefreshWebpackPlugin(),
        new ForkTsCheckerWebpackPlugin(),
    ].filter(Boolean),
    resolve: {
        extensions: ['.js', '.ts', '.tsx'],
    },
};
