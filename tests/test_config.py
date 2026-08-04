import os
import tempfile
from napari_flima.config import (
    IntroConfig,
    SingleFileConfig,
    FileSelectionConfig,
    CursorConfig,
    SegmentationConfig,
    ReportConfig,
    DownstreamConfig,
    FLIMAnalysisConfig,
    load_config_from_yaml,
    save_config_to_yaml,
)


def test_default_config():
    config = FLIMAnalysisConfig()
    assert config.intro.flim_type == "TCSPC FLIM"
    assert config.intro.laser_frequency == 80
    assert config.intro.harmonic == 1
    assert config.intro.calculate_gs is True
    assert config.file_selection.known_groups == ["None", "Condition 1", "Condition 2"]
    assert config.downstream.segmentation.min_size == 50
    assert config.downstream.segmentation.threshold == 75
    assert config.downstream.report.export_intensity is True


def test_custom_config_yaml_roundtrip():
    custom_intro = IntroConfig(
        flim_type="FD FLIM",
        laser_frequency=40,
        harmonic=2,
        g_offset=100.0,
        s_offset=200.0,
        stack_size=10,
        num_channels=2,
        channel_assignments=["Intensity", "G-values"],
        calculate_gs=False,
    )

    custom_file_selection = FileSelectionConfig(
        known_groups=["GroupA", "GroupB"],
        files={
            "sample1.tif": SingleFileConfig(
                file_name="sample1.tif",
                group="GroupA",
                mask_layer="mask1.tif",
                threshold_lower=10,
                threshold_upper=2000,
            ),
            "sample2.tif": SingleFileConfig(
                file_name="sample2.tif",
                group="GroupB",
                mask_layer="None",
                threshold_lower=0,
                threshold_upper=4095,
            ),
        },
    )

    custom_cursors = [
        CursorConfig(
            active=True,
            color="red",
            radius=0.1,
            g_value=0.5,
            s_value=0.4,
            tau_m=2.5,
            tau_p=2.3,
        ),
        CursorConfig(
            active=False,
            color="green",
            radius=0.05,
            g_value=0.2,
            s_value=0.3,
            tau_m=1.8,
            tau_p=1.6,
        ),
    ]

    custom_segmentation = SegmentationConfig(
        min_size=100,
        threshold=80,
        iou_threshold=0.5,
        max_dist=15,
        min_persist=20,
    )

    custom_report = ReportConfig(
        export_intensity=True,
        export_flim=False,
        export_gs=True,
        export_downstream=True,
        comparison_group="GroupA",
        export_directory="/tmp/export",
    )

    config = FLIMAnalysisConfig(
        intro=custom_intro,
        file_selection=custom_file_selection,
        downstream=DownstreamConfig(
            segmentation=custom_segmentation,
            cursors=custom_cursors,
            report=custom_report,
        ),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "test_config.yaml")
        save_config_to_yaml(config, yaml_path)

        assert os.path.exists(yaml_path)

        loaded_config = load_config_from_yaml(yaml_path)

        # Intro assertion
        assert loaded_config.intro.flim_type == "FD FLIM"
        assert loaded_config.intro.laser_frequency == 40
        assert loaded_config.intro.harmonic == 2
        assert loaded_config.intro.g_offset == 100.0
        assert loaded_config.intro.s_offset == 200.0
        assert loaded_config.intro.stack_size == 10
        assert loaded_config.intro.num_channels == 2
        assert loaded_config.intro.channel_assignments == ["Intensity", "G-values"]
        assert loaded_config.intro.calculate_gs is False

        # File Selection assertion
        assert loaded_config.file_selection.known_groups == ["GroupA", "GroupB"]
        assert "sample1.tif" in loaded_config.file_selection.files
        f1 = loaded_config.file_selection.files["sample1.tif"]
        assert f1.group == "GroupA"
        assert f1.mask_layer == "mask1.tif"
        assert f1.threshold_lower == 10
        assert f1.threshold_upper == 2000

        # Downstream Cursors assertion
        assert len(loaded_config.downstream.cursors) == 2
        c1 = loaded_config.downstream.cursors[0]
        assert c1.active is True
        assert c1.color == "red"
        assert c1.radius == 0.1
        assert c1.g_value == 0.5
        assert c1.tau_m == 2.5

        # Downstream Segmentation assertion
        seg = loaded_config.downstream.segmentation
        assert seg.min_size == 100
        assert seg.threshold == 80
        assert seg.iou_threshold == 0.5

        # Downstream Report assertion
        rep = loaded_config.downstream.report
        assert rep.export_flim is False
        assert rep.export_downstream is True
        assert rep.comparison_group == "GroupA"


if __name__ == "__main__":
    test_default_config()
    test_custom_config_yaml_roundtrip()
