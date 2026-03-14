# Search and Catalog Management

## Overview

The search and catalog infrastructure is responsible for making products discoverable and purchasable on the ShopStream storefront. This encompasses the product catalog management workflow, search indexing pipeline, relevance ranking, faceted navigation, autocomplete, and catalog analytics. The search system processes approximately 50 million search queries per day and indexes 8 million product SKUs.

## Catalog Management Workflow

### Product Creation Flow
1. **Draft**: Merchant creates a product via Portal or API. Status starts as DRAFT.
2. **Variant Setup**: At least one ProductVariant must be created with SKU, price, and options.
3. **Image Upload**: Product images are uploaded to the media-service, which generates size variants and CDN URLs.
4. **Category Assignment**: Product is assigned to 1-5 leaf categories from the platform taxonomy.
5. **Validation**: Automated checks verify title length, description format, image quality, price validity, and category-specific required attributes.
6. **Review** (first-time merchants): First 5 products undergo manual catalog review (24-48 hours).
7. **Activation**: Product status changes to ACTIVE, triggering search index update.

### Product Update Flow
- Title, description, and pricing changes take effect immediately on the storefront
- Category changes trigger re-indexing and may change tax treatment
- Price changes update the product in the search index within 15 minutes
- Stock changes (via Inventory entity) update the storefront availability in near-real-time (<500ms)

### Product Archival
- Merchants can archive products (status → ARCHIVED) via Portal or API
- Archived products are removed from the search index within 15 minutes
- Historical order references to archived products are preserved (product_name and variant_name are snapshotted on OrderLine)
- Reviews on archived products remain visible for 2 years before archival

## Search Architecture

### Elasticsearch Configuration
- **Cluster**: 3-node Elasticsearch 8.x cluster on AWS (r6g.2xlarge instances)
- **Indices**:
  - `products` — main product index with nested variant data
  - `suggestions` — autocomplete index with edge n-gram tokenization
  - `search_logs` — real-time search analytics
- **Shards**: 6 primary shards, 1 replica per shard for the products index
- **Refresh interval**: 1 second (near-real-time indexing)
- **Mapping**: Custom analyzers for multi-language support with language-specific stemmers

### Product Indexing Pipeline
1. Catalog-service publishes product.created / product.updated events to the catalog-events SNS topic
2. Product-indexer worker subscribes to the topic and processes events
3. Worker enriches the product data with: category hierarchy, merchant info, current inventory status, average rating
4. Enriched document is indexed into Elasticsearch
5. For bulk operations (initial index, reindex), a batch indexer processes from the database directly
6. Index health is monitored: document count should match active product count (within 0.1%)

### Product Document Schema
The Elasticsearch product document includes:
- **Core fields**: product_id, title, description, brand, base_price, status
- **Variant data** (nested): variant_id, sku, price, option values, inventory status
- **Category data**: category names, category path (for breadcrumbs)
- **Merchant data**: merchant display_name, rating, fulfillment speed
- **Computed fields**: average_rating, review_count, total_sold (30-day), discount_percentage
- **Facet fields**: brand, price_range, rating_bucket, shipping_speed, category_path

## Search Relevance

### Ranking Algorithm
Search results are ranked using a custom relevance scoring formula:

```
final_score =
    0.40 * text_relevance       # BM25 match on title, description, brand
  + 0.15 * popularity_score     # Based on 30-day sales velocity
  + 0.15 * rating_score         # average_rating * log(review_count + 1)
  + 0.10 * freshness_score      # Boost for recently published products
  + 0.10 * price_competitiveness # Position in category price distribution
  + 0.05 * fulfillment_score    # SFN products and fast-shipping merchants boosted
  + 0.05 * image_quality_score  # Products with 3+ images and high-res photos boosted
```

### Text Relevance (BM25)
- Title matches receive 3x boost over description matches
- Brand exact matches receive 5x boost
- Synonym expansion (e.g., "laptop" → "notebook", "couch" → "sofa")
- Spell correction with Levenshtein distance <= 2
- Multi-language analysis with language detection per product

### Search Features
- **Autocomplete**: Edge n-gram tokenization, responds in <50ms, shows top 8 suggestions
- **Faceted Search**: Dynamic facets based on category (e.g., Electronics shows brand, screen_size; Clothing shows brand, size, color)
- **Price Range Filter**: Supports min/max price slider
- **Rating Filter**: Filter by minimum star rating
- **Shipping Speed Filter**: Economy, Standard, Express, Same-Day
- **Sort Options**: Relevance (default), Price (low-high), Price (high-low), Rating, Newest

### Zero-Result Handling
When a search returns zero results:
1. System attempts spell correction and retries
2. If still zero: broadens the search by removing filters
3. Suggests related categories ("Did you mean...?")
4. Zero-result queries are logged and reported to the catalog team weekly
5. Persistent zero-result queries (>100 occurrences/week) indicate catalog gaps

## Catalog Analytics

### Key Metrics
- **Search-to-Click Rate (CTR)**: Percentage of searches resulting in a product click. Target: >30%.
- **Search-to-Purchase Rate**: Percentage of searches resulting in an order. Target: >5%.
- **Zero-Result Rate**: Percentage of searches returning no results. Target: <3%.
- **Average Search Response Time**: Target: <200ms at p50, <500ms at p99.
- **Autocomplete Usage Rate**: Percentage of searches initiated from autocomplete suggestions.

### Most Searched Terms Dashboard
- Updated hourly with the top 100 search terms
- Includes: term, search count, CTR, conversion rate, average result count
- Used by the merchandising team for promotional planning and category management

### Catalog Coverage Analysis
- Weekly report comparing search demand (popular search terms) against catalog supply (matching products)
- Identifies high-demand categories with low product count
- Feeds into merchant recruitment strategy (which product categories to target for new merchants)

### Product Performance
- Per-product analytics: impressions, clicks, add-to-cart, purchases
- Conversion funnel analysis: search → product view → add to cart → checkout → order
- Low-performing products (high impressions, low clicks) flagged for listing quality review
- High-performing products boosted in category pages and related product sections

## Category Taxonomy

### Structure
The category tree has a maximum depth of 4 levels:
- **Level 0 (Root)**: Major divisions (Electronics, Clothing, Home & Garden, Sports, Beauty, etc.)
- **Level 1**: Subcategories (Electronics > Computers, Electronics > Audio, Electronics > Phones)
- **Level 2**: Product types (Computers > Laptops, Computers > Desktops, Computers > Tablets)
- **Level 3**: Specific types (Laptops > Gaming Laptops, Laptops > Business Laptops)

### Category Attributes
Each leaf category can define additional attributes that become available as product fields:
- **Electronics > Laptops**: screen_size (decimal, inches), processor (text), RAM (text), storage (text), battery_life (text)
- **Clothing > Tops**: material (text), care_instructions (text), fit_type (enum: slim/regular/relaxed)
- **Home > Furniture**: dimensions_cm (JSON), weight_kg (decimal), assembly_required (boolean), material (text)

### Category Management
- Categories are managed by the platform catalog team
- Merchants cannot create or modify categories
- New category requests are submitted through the Partner Portal
- Category changes trigger product re-indexing for affected products
- The category tree is reviewed quarterly for relevance and completeness

## Content Moderation

### Automated Checks
All product listings pass through automated content moderation:
1. **Prohibited content**: Weapons, drugs, counterfeit goods, adult content (when not in adult category)
2. **Trademark violations**: Brand name misuse, unauthorized brand claims
3. **Misleading content**: "100% organic" without certification, unsubstantiated health claims
4. **Title quality**: No ALL CAPS, no keyword stuffing, no promotional text ("SALE!", "FREE!")
5. **Image quality**: No watermarks, no collages, minimum resolution, no text overlay (except for book covers)

### Manual Review Queue
- Products flagged by automated checks enter a manual review queue
- Review SLA: 24 hours for standard, 4 hours for expedited (merchant request)
- Outcomes: APPROVE, REJECT (with reason), REQUEST_CHANGES (sent back to merchant)
- Repeat offenders (>3 rejected products) trigger merchant review

### Product Suspension
Products violating platform policies are suspended (status → SUSPENDED):
- Removed from search results immediately
- Existing links show "This product has been removed"
- Merchant notified with reason and appeal process
- Three product suspensions in 90 days triggers merchant-level review

## Performance Requirements

### Search Latency SLAs
| Percentile | Target | Alert Threshold |
|-----------|--------|-----------------|
| p50 | <100ms | >200ms |
| p95 | <300ms | >500ms |
| p99 | <500ms | >1000ms |

### Indexing SLAs
| Operation | Target | Alert Threshold |
|-----------|--------|-----------------|
| Single product index | <1 second | >5 seconds |
| Bulk reindex (full catalog) | <4 hours | >8 hours |
| Search availability | 99.95% uptime | <99.9% |

### Capacity Planning
- Current: ~50M queries/day, ~8M documents indexed
- Index size: ~25GB (products) + ~5GB (suggestions)
- Node RAM: 64GB per node (50% allocated to JVM heap)
- Disk: 500GB SSD per node (15% utilization)
- Growth: Plan for 30% YoY query growth, 40% YoY catalog growth
