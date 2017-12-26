import tensorflow as tf

from mrtoct import data
from mrtoct.model import losses


def cnn_model_fn(features, labels, mode, params):
  inputs = features['inputs']

  if params.data_format == 'channels_first':
    nchw_transform = data.transform.DataFormat2D('channels_first')
    nhwc_transform = data.transform.DataFormat2D('channels_last')

    outputs = params.generator_fn(nchw_transform(inputs), params.data_format)
    outputs = nhwc_transform(outputs)
  else:
    outputs = params.generator_fn(inputs)

  if tf.estimator.ModeKeys.PREDICT == mode:
    return tf.estimator.EstimatorSpec(mode, {
        'inputs': inputs, 'outputs': outputs})

  targets = labels['targets']

  tf.summary.image('inputs', inputs, max_outputs=1)
  tf.summary.image('outputs', outputs, max_outputs=1)
  tf.summary.image('targets', targets, max_outputs=1)
  tf.summary.image('residue', targets - outputs, max_outputs=1)

  mse = tf.losses.mean_squared_error(targets, outputs)
  mae = tf.losses.absolute_difference(targets, outputs)
  gdl = losses.gradient_difference_loss_2d(targets, outputs)

  tf.summary.scalar('mean_squared_error', mse)
  tf.summary.scalar('mean_absolute_error', mae)
  tf.summary.scalar('gradient_difference_loss', gdl)

  loss = 3 * mae + gdl

  tf.summary.scalar('total_loss', loss)

  vars = tf.trainable_variables()

  gdl_grad = tf.global_norm(tf.gradients(gdl, vars))
  mae_grad = tf.global_norm(tf.gradients(mae, vars))

  tf.summary.scalar('gradient_difference_loss_gradient', gdl_grad)
  tf.summary.scalar('mean_absolute_error_gradient', mae_grad)

  if tf.estimator.ModeKeys.EVAL == mode:
    return tf.estimator.EstimatorSpec(
        mode, {'outputs': outputs}, loss)

  optimizer = tf.train.AdamOptimizer(params.learn_rate, params.beta1_rate)

  train = optimizer.minimize(loss, tf.train.get_global_step())

  return tf.estimator.EstimatorSpec(
      mode, {'outputs': outputs}, loss, train)


def gan_model_fn(features, labels, mode, params):
  inputs = features['inputs']
  targets = labels['targets']

  if params.data_format == 'channels_first':
    in_transform = data.transform.DataFormat2D('channels_first')
    out_transform = data.transform.DataFormat2D('channels_last')
  else:
    in_transform = out_transform = lambda x: x

  def generator_fn(x):
    return params.generator_fn(x, params.data_format)

  def discriminator_fn(x, y):
    return params.discriminator_fn(x, y, params.data_format)

  gan_model = tf.contrib.gan.gan_model(
      generator_fn=generator_fn,
      discriminator_fn=discriminator_fn,
      real_data=in_transform(targets),
      generator_inputs=in_transform(inputs))

  gan_loss = tf.contrib.gan.gan_loss(
      model=gan_model,
      generator_loss_fn=params.generator_loss_fn,
      discriminator_loss_fn=params.discriminator_loss_fn,
  )

  outputs = out_transform(gan_model.generated_data)

  tf.summary.image('inputs', inputs, max_outputs=1)
  tf.summary.image('outputs', outputs, max_outputs=1)
  tf.summary.image('targets', targets, max_outputs=1)
  tf.summary.image('residue', targets - outputs, max_outputs=1)

  with tf.name_scope('loss'):
    mae = tf.norm(targets - outputs, ord=1)
    mse = tf.norm(targets - outputs, ord=2)
    gdl = tf.reduce_sum(tf.image.total_variation(targets - outputs))

    tf.summary.scalar('mean_squared_error', mse)
    tf.summary.scalar('mean_absolute_error', mae)
    tf.summary.scalar('gradient_difference_loss', gdl)

    loss = 3 * mae + gdl

    tf.summary.scalar('total_loss', loss)

    vars = tf.trainable_variables()

    gdl_grad = tf.global_norm(tf.gradients(gdl, vars))
    mae_grad = tf.global_norm(tf.gradients(mae, vars))
    mse_grad = tf.global_norm(tf.gradients(mse, vars))

    tf.summary.scalar('gradient_difference_loss_gradient', gdl_grad)
    tf.summary.scalar('mean_absolute_error_gradient', mae_grad)
    tf.summary.scalar('mean_squared_error_gradient', mse_grad)

    real_score = gan_model.discriminator_real_outputs
    fake_score = gan_model.discriminator_gen_outputs

    tf.summary.histogram('real_score', real_score)
    tf.summary.histogram('fake_score', fake_score)

    gan_loss = tf.contrib.gan.losses.combine_adversarial_loss(
        gan_loss=gan_loss,
        gan_model=gan_model,
        non_adversarial_loss=loss,
        weight_factor=params.weight_factor,
    )

  with tf.name_scope('train'):
    generator_optimizer = tf.train.AdamOptimizer(
        params.learn_rate, params.beta1_rate)
    discriminator_optimizer = tf.train.AdamOptimizer(
        params.learn_rate, params.beta1_rate)

    train = tf.contrib.gan.gan_train_ops(
        model=gan_model,
        loss=gan_loss,
        generator_optimizer=generator_optimizer,
        discriminator_optimizer=discriminator_optimizer)
    train_op = tf.group(*list(train))

  return tf.estimator.EstimatorSpec(
      mode, {'outputs': outputs}, loss, train_op)
