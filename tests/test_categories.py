from weld_data_workbench.domain.categories import (
    category_display_name,
    is_good_category,
    normalize_category,
)


def test_category_aliases() -> None:
    assert normalize_category("good") == "Good"
    assert normalize_category("Lack Of Fusion") == "Lack_of_Fusion"
    assert (
        normalize_category("Porosity w/ Excessive Penetration")
        == "Porosity_w_Excessive_Penetration"
    )
    assert normalize_category("Excessive Penetration") == "Excessive_Penetration"
    assert is_good_category("Normal")
    assert category_display_name("Crater_Cracks") == "Crater Cracks"


def test_unknown_category_is_preserved() -> None:
    assert normalize_category("Experimental defect") == "Experimental defect"
    assert normalize_category(None) is None
