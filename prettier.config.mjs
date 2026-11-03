/** @type {import("prettier").Config} */
export default {
  // Prettier defaults (double quotes, semicolons, trailing commas, 80 columns) are kept on
  // purpose: fewer settings to explain, and they match what create-next-app generates.
  plugins: ["prettier-plugin-tailwindcss"],
  tailwindStylesheet: "./apps/web/src/app/globals.css",
};
