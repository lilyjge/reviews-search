"""Sample optometrist reviews for offline testing without scraping."""

from reviews_search.models import Place, Review

DEMO_PLACES = [
    Place(
        place_id="demo_kw_vision",
        name="KW Vision Centre",
        address="123 King St W, Kitchener, ON",
        rating=4.6,
        review_count=120,
        maps_url="https://www.google.com/maps",
        category="optometrist",
    ),
    Place(
        place_id="demo_uwaterloo_eye",
        name="University Eye Care",
        address="200 University Ave W, Waterloo, ON",
        rating=4.4,
        review_count=85,
        maps_url="https://www.google.com/maps",
        category="optometrist",
    ),
    Place(
        place_id="demo_lenscraft",
        name="LensCraft Optometry",
        address="45 Erb St E, Waterloo, ON",
        rating=4.8,
        review_count=200,
        maps_url="https://www.google.com/maps",
        category="optometrist",
    ),
]

DEMO_REVIEWS = [
    Review(
        review_id="demo_kw_vision::r1",
        place_id="demo_kw_vision",
        place_name="KW Vision Centre",
        text="Dr. Chen explained ortho-k lenses clearly. My teen's myopia seems stable after 6 months of overnight wear.",
        rating=5,
        published_date="3 months ago",
        reviewer_name="Sarah M.",
    ),
    Review(
        review_id="demo_kw_vision::r2",
        place_id="demo_kw_vision",
        place_name="KW Vision Centre",
        text="Great staff and thorough eye exam. They don't offer orthokeratology here, only regular contacts.",
        rating=4,
        published_date="1 year ago",
        reviewer_name="James L.",
    ),
    Review(
        review_id="demo_uwaterloo_eye::r1",
        place_id="demo_uwaterloo_eye",
        place_name="University Eye Care",
        text="I got fitted for Ortho-K here. Took a few nights to adjust but vision is 20/20 during the day without glasses.",
        rating=5,
        published_date="2 weeks ago",
        reviewer_name="Priya K.",
    ),
    Review(
        review_id="demo_uwaterloo_eye::r2",
        place_id="demo_uwaterloo_eye",
        place_name="University Eye Care",
        text="Long wait times but friendly optometrist. Standard contact lens fitting only.",
        rating=3,
        published_date="4 months ago",
        reviewer_name="Mike T.",
    ),
    Review(
        review_id="demo_lenscraft::r1",
        place_id="demo_lenscraft",
        place_name="LensCraft Optometry",
        text="Best orthokeratology program in Waterloo region. They monitor corneal topography every visit.",
        rating=5,
        published_date="1 month ago",
        reviewer_name="Anna R.",
    ),
    Review(
        review_id="demo_lenscraft::r2",
        place_id="demo_lenscraft",
        place_name="LensCraft Optometry",
        text="Frames selection is huge. Didn't discuss overnight lenses but happy with new progressive glasses.",
        rating=5,
        published_date="6 months ago",
        reviewer_name="David W.",
    ),
]
