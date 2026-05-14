export type County = {
  name: string;
  state: string;
  fips: string;
  zillowRegionName: string;
};

export type Market = {
  slug: string;
  label: string;
  state: string;
  counties: County[];
};

export const TAMPA_BAY: Market = {
  slug: "tampa-bay",
  label: "Tampa Bay",
  state: "FL",
  counties: [
    { name: "Hillsborough", state: "FL", fips: "12057", zillowRegionName: "Hillsborough County" },
    { name: "Pinellas", state: "FL", fips: "12103", zillowRegionName: "Pinellas County" },
    { name: "Pasco", state: "FL", fips: "12101", zillowRegionName: "Pasco County" },
    { name: "Hernando", state: "FL", fips: "12053", zillowRegionName: "Hernando County" },
  ],
};

export const MARKETS: Market[] = [TAMPA_BAY];
