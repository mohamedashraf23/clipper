from clipper import social


def test_template_posts_without_ai(transcript):
    picks = [{"start": 0.0, "end": 9.0, "title": "Why this happens", "hook": "Have you ever wondered?"}]
    out = social.write_posts(picks, transcript, "My Podcast Episode", "talk", log=lambda *a, **k: None)
    post = out[0]["post"]
    assert post["caption"] == "Have you ever wondered?"
    assert "#shorts" in post["hashtags"] and len(post["hashtags"]) <= social.MAX_TAGS
    assert all(t.startswith("#") and " " not in t for t in post["hashtags"])


def test_arabic_and_gameplay_tags():
    p = {"start": 0, "end": 5, "title": "صوت هيفا", "hook": "بتحبها"}
    post = social._template(p, "gameplay", "ar", "حلقة")
    assert "#gaming" in post["hashtags"] and "#اكسبلور" in post["hashtags"]


def test_post_text_layout():
    text = social.post_text({"caption": "Watch this", "hashtags": ["#a", "#b"]})
    assert text == "Watch this\n\n#a #b\n"


def test_clean_tag():
    assert social._clean_tag(" #Grand Theft-Auto ") == "#GrandTheftAuto"
    assert social._clean_tag("###") == ""
