import React from "react";
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { render, screen, fireEvent } from "@testing-library/react";
import { it, expect } from "vitest";
import DestinationPhoto, { photoFor } from "./DestinationPhoto.jsx";
import photos from "./data/destinationPhotos.json";

const photo = Object.values(photos)[0];
const item = {
  destination_id: photo.destination_id,
  name: photo.name,
  kind: "attraction",
  country: "Pakistan",
  data_source: "pakistan_tourism",
};

it("requires exact catalog identity and compatible country/source/type", () => {
  expect(photoFor(item)).toBe(photo);
  expect(
    photoFor({ ...item, destination_id: "unverified", name: item.name }),
  ).toBeNull();
  expect(photoFor({ ...item, country: "United States" })).toBeNull();
  expect(photoFor({ ...item, kind: "hotel" })).toBeNull();
  expect(photoFor({ ...item, data_source: "tripadvisor" })).toBeNull();
});

it("renders responsive lazy photographs with visible source and license attribution", () => {
  render(<DestinationPhoto item={item} />);
  const image = screen.getByAltText(photo.caption);
  expect(image).toHaveAttribute("loading", "lazy");
  expect(image).toHaveAttribute("decoding", "async");
  expect(image).toHaveAttribute(
    "srcset",
    photo.variants.map((v) => `${v.src} ${v.width}w`).join(", "),
  );
  expect(image).toHaveAttribute("width", "960");
  expect(
    screen.getByRole("link", { name: /Wikimedia Commons/ }),
  ).toHaveAttribute("href", photo.source_url);
  expect(screen.getByRole("link", { name: photo.license })).toHaveAttribute(
    "href",
    photo.license_url,
  );
  expect(screen.getByText(photo.changes)).toBeInTheDocument();
});

it("falls back on load failure and resets for another destination", () => {
  const { rerender } = render(<DestinationPhoto item={item} />);
  fireEvent.error(screen.getByAltText(photo.caption));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(
    screen.getByText(/Illustration · photo unavailable/),
  ).toBeInTheDocument();
  const next = Object.values(photos)[1];
  rerender(
    <DestinationPhoto
      item={{ ...item, destination_id: next.destination_id, name: next.name }}
    />,
  );
  expect(screen.getByAltText(next.caption)).toBeInTheDocument();
});

it("uses an explicitly illustrative fallback for unverified destinations", () => {
  render(<DestinationPhoto item={{ ...item, destination_id: "unverified" }} />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText(/no verified photo yet/)).toBeInTheDocument();
});

it.each(["detail", "itinerary"])(
  "reuses identical verified metadata in %s views",
  (variant) => {
    const { container } = render(
      <DestinationPhoto item={item} variant={variant} />,
    );
    expect(container.querySelector(`.photo-${variant}`)).toBeInTheDocument();
    expect(screen.getByAltText(photo.caption)).toHaveAttribute(
      "src",
      photo.variants.at(-1).src,
    );
  },
);

it("ships all curated sources, local variants, and unchanged asset checksums", () => {
  const sources = JSON.parse(
    readFileSync(`${process.cwd()}/photo_sources.json`, "utf8"),
  );
  expect(Object.values(photos)).toHaveLength(sources.length);
  expect(sources.length).toBeGreaterThanOrEqual(16);
  for (const [id, entry] of Object.entries(photos)) {
    expect(entry.destination_id).toBe(id);
    expect(entry.author).toBeTruthy();
    expect(entry.source_url).toMatch(
      /^https:\/\/commons\.wikimedia\.org\/wiki\/File:/,
    );
    expect(entry.license_url).toMatch(
      /^https:\/\/creativecommons\.org\/licenses\//,
    );
    expect(entry.variants.length).toBe(2);
    for (const variant of entry.variants) {
      const path = `${process.cwd()}/public${variant.src}`;
      expect(existsSync(path)).toBe(true);
      const bytes = readFileSync(path);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(
        variant.sha256,
      );
      expect(bytes.length).toBe(variant.bytes);
      expect(variant.width).toBeLessThanOrEqual(entry.native_width || 960);
    }
  }
});
