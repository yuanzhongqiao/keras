import os

import numpy as np
import pytest

from keras import backend
from keras import constraints
from keras import layers
from keras import models
from keras import saving
from keras.testing import test_case


class EmbeddingTest(test_case.TestCase):
    @pytest.mark.requires_trainable_backend
    def test_embedding_basics(self):
        self.run_layer_test(
            layers.Embedding,
            {"input_dim": 4, "output_dim": 3},
            input_shape=(2,),
            input_dtype="int32",
            expected_output_shape=(2, 3),
            expected_num_trainable_weights=1,
            expected_num_non_trainable_weights=0,
            expected_num_seed_generators=0,
            expected_num_losses=0,
            supports_masking=False,
        )
        self.run_layer_test(
            layers.Embedding,
            {"input_dim": 5, "output_dim": 4, "mask_zero": True},
            input_shape=(2, 3),
            input_dtype="int64",
            expected_output_shape=(2, 3, 4),
            expected_num_trainable_weights=1,
            expected_num_non_trainable_weights=0,
            expected_num_seed_generators=0,
            expected_num_losses=0,
            supports_masking=True,
        )

    @pytest.mark.skipif(
        not backend.SUPPORTS_SPARSE_TENSORS,
        reason="Backend does not support sparse tensors.",
    )
    def test_sparse(self):
        self.run_layer_test(
            layers.Embedding,
            {"input_dim": 5, "output_dim": 4},
            input_shape=(2, 3),
            input_dtype="int32",
            input_sparse=True,
            expected_output_shape=(2, 3, 4),
            expected_num_trainable_weights=1,
            expected_num_non_trainable_weights=0,
            expected_num_seed_generators=0,
            expected_num_losses=0,
            supports_masking=False,
        )

    def test_correctness(self):
        layer = layers.Embedding(input_dim=3, output_dim=2)
        layer.build()
        layer.embeddings.assign(np.array([[0.0, 0.0], [2.0, 2.0], [3.0, 3.0]]))
        out = layer(np.array([2, 1, 0]))
        self.assertAllClose(out, np.array([[3.0, 3.0], [2.0, 2.0], [0.0, 0.0]]))

    @pytest.mark.skipif(
        not backend.SUPPORTS_SPARSE_TENSORS,
        reason="Backend does not support sparse tensors.",
    )
    def test_correctness_sparse(self):
        import tensorflow as tf

        layer = layers.Embedding(input_dim=3, output_dim=2)
        layer.build()
        layer.embeddings.assign(np.array([[0.0, 0.0], [2.0, 2.0], [3.0, 3.0]]))
        x = tf.SparseTensor(
            indices=[[0, 0], [1, 2]], values=[2, 1], dense_shape=(2, 3)
        )
        self.assertAllClose(
            layer(x),
            np.array(
                [
                    [[3.0, 3.0], [0.0, 0.0], [0.0, 0.0]],
                    [[0.0, 0.0], [0.0, 0.0], [2.0, 2.0]],
                ]
            ),
        )

    def test_masking(self):
        layer = layers.Embedding(input_dim=3, output_dim=2, mask_zero=True)
        layer.build()
        out = layer.compute_mask(np.array(([2, 1, 0])))
        self.assertAllClose(out, np.array([True, True, False]))

    def test_compute_mask_no_masking(self):
        layer = layers.Embedding(input_dim=3, output_dim=2, mask_zero=False)
        input_data = np.array([2, 1, 0])
        mask = layer.compute_mask(input_data)
        self.assertIsNone(mask)

    def test_embedding_constraints(self):
        layer = layers.Embedding(3, 2, embeddings_constraint="non_neg")
        layer.build((None, 2))
        self.assertIsInstance(layer.embeddings.constraint, constraints.NonNeg)

    @pytest.mark.requires_trainable_backend
    def test_enable_lora(self):
        layer = layers.Embedding(10, 16)
        layer.build()
        layer.enable_lora(4)
        self.assertLen(layer.trainable_weights, 2)
        self.assertLen(layer.non_trainable_weights, 1)
        # Try eager call
        x = np.random.randint(0, 9, size=(64, 3))
        y = np.random.random((64, 3, 16))
        _ = layer(x[:2])

        init_lora_a_embeddings_value = layer.lora_embeddings_a.numpy()
        init_lora_b_embeddings_value = layer.lora_embeddings_b.numpy()

        # Try calling fit()
        model = models.Sequential(
            [
                layer,
            ]
        )
        model.compile(optimizer="sgd", loss="mse")
        model.fit(x, y)

        final_lora_a_embeddings_value = layer.lora_embeddings_a.numpy()
        final_lora_b_embeddings_value = layer.lora_embeddings_b.numpy()
        diff_a = np.max(
            np.abs(init_lora_a_embeddings_value - final_lora_a_embeddings_value)
        )
        diff_b = np.max(
            np.abs(init_lora_b_embeddings_value - final_lora_b_embeddings_value)
        )
        self.assertGreater(diff_a, 0.0)
        self.assertGreater(diff_b, 0.0)

        # Try saving and reloading the model
        temp_filepath = os.path.join(self.get_temp_dir(), "lora_model.keras")
        model.save(temp_filepath)

        new_model = saving.load_model(temp_filepath)
        self.assertFalse(new_model.layers[0].lora_enabled)
        self.assertAllClose(model.predict(x), new_model.predict(x))

        # Try saving and reloading the model's weights only
        temp_filepath = os.path.join(
            self.get_temp_dir(), "lora_model.weights.h5"
        )
        model.save_weights(temp_filepath)

        # Load the file into a fresh, non-lora model
        new_model = models.Sequential(
            [
                layers.Input((3,), dtype="int32"),
                layers.Embedding(10, 16),
            ]
        )
        new_model.load_weights(temp_filepath)
        self.assertAllClose(model.predict(x), new_model.predict(x))

        # Try loading a normal checkpoint into a lora model
        new_model.save_weights(temp_filepath)
        model.load_weights(temp_filepath)
        self.assertAllClose(model.predict(x), new_model.predict(x))

    @pytest.mark.requires_trainable_backend
    def test_lora_rank_argument(self):
        self.run_layer_test(
            layers.Embedding,
            init_kwargs={"input_dim": 5, "output_dim": 4, "lora_rank": 2},
            input_shape=(2, 3),
            input_dtype="int32",
            expected_output_shape=(2, 3, 4),
            expected_num_trainable_weights=2,
            expected_num_non_trainable_weights=1,
            expected_num_seed_generators=0,
            expected_num_losses=0,
            supports_masking=False,
        )

    def test_enable_lora_with_embeddings_constraint(self):
        layer = layers.Embedding(
            input_dim=10, output_dim=16, embeddings_constraint="max_norm"
        )
        with self.assertRaisesRegex(
            ValueError, "incompatible with embedding constraints"
        ):
            layer.enable_lora(rank=2)

    def test_enable_lora_on_unbuilt_layer(self):
        layer = layers.Embedding(input_dim=10, output_dim=16)
        with self.assertRaisesRegex(
            ValueError, "Cannot enable lora on a layer that isn't yet built"
        ):
            layer.enable_lora(rank=2)

    def test_enable_lora_when_already_enabled(self):
        layer = layers.Embedding(input_dim=10, output_dim=16)
        layer.build()
        layer.enable_lora(rank=2)
        with self.assertRaisesRegex(ValueError, "lora is already enabled"):
            layer.enable_lora(rank=2)
