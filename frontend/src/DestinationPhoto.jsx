import React, { useState } from "react";
import photos from "./data/destinationPhotos.json";

export function photoFor(item) {
  const photo = photos[item.destination_id];
  if (
    !photo ||
    item.country !== photo.country ||
    item.kind !== photo.kind ||
    (item.data_source && item.data_source !== photo.data_source)
  )
    return null;
  return photo;
}

function Photo({ item, photo, variant }) {
  const [failed, setFailed] = useState(false);
  if (!photo || failed) {
    return (
      <div
        className={`card-art photo-fallback ${item.kind === "hotel" ? "hotel" : "land"}`}
      >
        <span aria-hidden="true">{item.kind === "hotel" ? "⌂" : "↗"}</span>
        <small>
          Illustration ·{" "}
          {failed ? "photo unavailable" : "no verified photo yet"}
        </small>
      </div>
    );
  }
  const largest = photo.variants.at(-1);
  return (
    <figure className={`destination-photo photo-${variant}`}>
      <img
        src={largest.src}
        srcSet={photo.variants.map((v) => `${v.src} ${v.width}w`).join(", ")}
        sizes={
          variant === "card"
            ? "(max-width: 700px) calc(100vw - 32px), (max-width: 1000px) 45vw, 400px"
            : "(max-width: 700px) calc(100vw - 64px), 700px"
        }
        width={largest.width}
        height={largest.height}
        alt={photo.caption}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
      <figcaption>
        <a href={photo.source_url} target="_blank" rel="noopener noreferrer">
          Photo: {photo.author} / Wikimedia Commons
        </a>
        {" · "}
        <a href={photo.license_url} target="_blank" rel="noopener noreferrer">
          {photo.license}
        </a>
        <span>{photo.changes}</span>
      </figcaption>
    </figure>
  );
}

export default function DestinationPhoto({ item, variant = "card" }) {
  return (
    <Photo
      key={item.destination_id}
      item={item}
      photo={photoFor(item)}
      variant={variant}
    />
  );
}
