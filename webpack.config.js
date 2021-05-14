const path = require('path');
const ReactRefreshWebpackPlugin = require('@pmmmwh/react-refresh-webpack-plugin');
const ForkTsCheckerWebpackPlugin = require('fork-ts-checker-webpack-plugin');
// const HtmlWebpackPlugin = require('html-webpack-plugin');
const ReactRefreshTypeScript = require('react-refresh-typescript').default;

const isDevelopment = process.env.NODE_ENV !== 'production';

module.exports = {
    mode: isDevelopment ? 'development' : 'production',
    entry: {
        main: './src/client/entry.tsx',
    },
    devServer: {

    },
    module: {
        rules: [
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
